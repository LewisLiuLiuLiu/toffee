"""Xyce shared-library simulator backend for toffee."""

import asyncio
import os
import sys
import tempfile

from ..simulator import Simulator
from .analog_backend import AnalogBackend
from .xyce_prn_parser import XycePrnParser

# Allow importing the official Xyce Python wrapper without installing it
_DEFAULT_XYCE_SHARE = os.environ.get(
    "XYCE_SHARE", "/mnt/d/ongoingProjects/openEDA/install/xyce/share"
)
_DEFAULT_XYCE_LIB = os.environ.get(
    "XYCE_LIB", "/mnt/d/ongoingProjects/openEDA/install/xyce/lib"
)

if _DEFAULT_XYCE_SHARE not in sys.path:
    sys.path.insert(0, _DEFAULT_XYCE_SHARE)

from xyce_interface import xyce_interface


class XyceSimulator(Simulator, AnalogBackend):
    """
    Xyce backend using the official ctypes-based Python interface.

    This backend supports true step-by-step simulation via
    ``simulateUntil()``, enabling lazy synchronization in mixed-signal
    environments.
    """

    def __init__(self, netlist_path: str, libdir: str = None, analysis_cmds: list = None,
                 port_mapping=None):
        self._original_netlist = netlist_path
        if libdir is None:
            libdir = _DEFAULT_XYCE_LIB
        self._xyce = xyce_interface(libdir=libdir)
        if hasattr(self._xyce, "setReportHandler"):
            self._xyce.setReportHandler()
        self._clock_event = asyncio.Event()
        self._current_time = 0.0
        self._prev_adc_states: dict = {}
        self._yadc_to_node: dict = {}
        self._yadc_overrides: dict = {}
        self._vdd: float = 1.8

        # Build YADC mapping from PortMapping if provided
        if port_mapping is not None:
            self._build_yadc_to_node(port_mapping)

        # Prepare netlist for Xyce initialization.
        # Both analysis_cmds and port_mapping may require a temporary copy.
        if analysis_cmds or port_mapping is not None:
            self._temp_dir = tempfile.mkdtemp(prefix="toffee_xyce_")

            # First: inject YDAC/YADC if port_mapping is present
            if port_mapping is not None:
                netlist_path = self._inject_ydac_yadc(netlist_path, port_mapping)

            # Then: merge analysis_cmds if present (may modify the same temp file)
            if analysis_cmds:
                netlist_path = self._merge_netlist(netlist_path, analysis_cmds)

            self._netlist_path = netlist_path
        else:
            self._temp_dir = None
            self._netlist_path = netlist_path

        status = self._xyce.initialize([netlist_path])
        if status != 1:
            msg = ""
            if hasattr(self._xyce, "getLastError"):
                msg = self._xyce.getLastError()
            raise RuntimeError(
                f"Xyce initialize failed for {netlist_path}: {msg}" if msg
                else f"Xyce initialize failed for {netlist_path} (status={status})"
            )

    def _merge_netlist(self, original: str, analysis_cmds: list) -> str:
        """Inject analysis commands before the final .end directive."""
        temp_path = os.path.join(self._temp_dir, "run.cir")
        with open(original, "r") as src:
            lines = src.readlines()

        with open(temp_path, "w") as dst:
            end_seen = False
            for line in lines:
                stripped = line.strip().lower()
                if stripped == ".end":
                    for cmd in analysis_cmds:
                        dst.write(f"{cmd}\n")
                    dst.write(".end\n")
                    end_seen = True
                    break
                else:
                    dst.write(line)
            if not end_seen:
                for cmd in analysis_cmds:
                    dst.write(f"{cmd}\n")
                dst.write(".end\n")
        return temp_path

    def _build_yadc_to_node(self, port_mapping) -> None:
        """Build _yadc_to_node mapping from PortMapping's a2d entries.

        Iterates over ``port_mapping.iter_a2d()`` and, for entries that
        specify a ``yadc_device``, maps the YADC device name to the
        analog variable name (used as the key in ``_yadc_overrides`` so
        that ``read(analog_name)`` returns the quantised voltage).
        """
        for analog_name, _digital_name, _threshold, _invert, yadc_device in port_mapping.iter_a2d():
            if yadc_device:
                self._yadc_to_node[yadc_device] = analog_name

    @staticmethod
    def _strip_v_notation(name: str) -> str:
        """Strip V()/I() SPICE notation to get a bare node name.

        ``"V(out)"`` -> ``"out"``,  ``"vout"`` -> ``"vout"``.
        """
        for prefix in ("V(", "v(", "I(", "i("):
            if name.startswith(prefix) and name.endswith(")"):
                return name[len(prefix):-1]
        return name

    @staticmethod
    def _find_vsrc_node(lines: list[str], vsrc_name: str) -> str | None:
        """Find a VSRC instance line and return its positive node name.

        SPICE VSRC syntax: ``V<name> <pos_node> <neg_node> ...``
        Matching is case-insensitive on the instance name.
        Returns ``None`` if no matching VSRC is found.
        """
        target = vsrc_name.lower().strip()
        for line in lines:
            tokens = line.split()
            if not tokens:
                continue
            # VSRC lines start with 'V' or 'v'
            first = tokens[0]
            if not first or first[0].lower() != "v":
                continue
            if first.lower() == target:
                if len(tokens) >= 3:
                    return tokens[1]  # positive node
        return None

    def _inject_ydac_yadc(self, original_path: str, port_mapping) -> str:
        """Inject YDAC/YADC device lines into a copy of the netlist.

        For each d2a entry the corresponding VSRC line is located in the
        original netlist, its positive node extracted, and the VSRC replaced
        by a YDAC device named after the *analog_name* (e.g. ``V_IN``).
        This keeps the device name consistent with what
        ``updateTimeVoltagePairs()`` expects (``YDAC!<analog_name>``).

        For each a2d entry with ``yadc_device`` set, a YADC line is added.
        ``V()`` / ``I()`` notation in the analog_name is stripped so that
        Xyce receives a plain node name.

        Returns the path to the modified netlist file.
        """
        temp_path = os.path.join(self._temp_dir, "yadc_injected.cir")

        with open(original_path, "r") as src:
            lines = src.readlines()

        # --- Determine which VSRC names to replace and their node mappings ---
        d2a_vsrc_names: set[str] = set()          # lowercase VSRC instance names
        d2a_vsrc_to_node: dict[str, str] = {}      # lowercase name -> positive node
        for _d_name, analog_name, _scale, _offset in port_mapping.iter_d2a():
            node = self._find_vsrc_node(lines, analog_name)
            if node is not None:
                d2a_vsrc_names.add(analog_name.lower().strip())
                d2a_vsrc_to_node[analog_name.lower().strip()] = node

        # --- Build injection lines ---
        inject_lines: list[str] = []

        # YDAC lines for d2a entries (use analog_name as device, extracted node)
        for _d_name, analog_name, _scale, _offset in port_mapping.iter_d2a():
            node = d2a_vsrc_to_node.get(analog_name.lower().strip())
            if node is not None:
                inject_lines.append(f"ydac {analog_name} {node} 0")
            else:
                # Fallback: use analog_name as both device and node
                inject_lines.append(f"ydac {analog_name} {analog_name} 0")

        # YADC lines for a2d entries (strip V() notation for node name)
        for analog_name, _digital_name, _threshold, _invert, yadc_device in port_mapping.iter_a2d():
            if yadc_device:
                node = self._strip_v_notation(analog_name)
                inject_lines.append(f"yadc {yadc_device} {node} 0")

        # --- Write modified netlist (remove replaced VSRC lines) ---
        with open(temp_path, "w") as dst:
            end_seen = False
            for line in lines:
                stripped = line.strip().lower()
                if stripped == ".end":
                    for inject in inject_lines:
                        dst.write(f"{inject}\n")
                    dst.write(".end\n")
                    end_seen = True
                    break
                else:
                    # Skip VSRC lines that are being replaced by YDAC
                    tokens = line.split()
                    if (tokens
                            and tokens[0][0].lower() == "v"
                            and tokens[0].lower() in d2a_vsrc_names):
                        continue  # remove original VSRC line
                    dst.write(line)
            if not end_seen:
                for inject in inject_lines:
                    dst.write(f"{inject}\n")
                dst.write(".end\n")

        return temp_path

    def step_time(self, dt: float) -> None:
        """Advance simulation by *dt* seconds."""
        requested = self._current_time + dt
        self.advance_to(requested)

    def step(self, cycles: int = 1) -> None:
        """Convenience wrapper: advance by ``cycles * 1 ns``."""
        self.step_time(1e-9 * cycles)

    def advance_to(self, time: float) -> None:
        """Lazy synchronization: advance Xyce to *time* only if behind."""
        if time > self._current_time:
            status, actual = self._xyce.simulateUntil(time)
            if status != 1:
                msg = ""
                if hasattr(self._xyce, "getLastError"):
                    msg = self._xyce.getLastError()
                raise RuntimeError(
                    f"Xyce simulateUntil failed at {time}: {msg}" if msg
                    else f"Xyce simulateUntil failed at {time} (status={status})"
                )
            self._current_time = actual

    @property
    def clock_event(self) -> asyncio.Event:
        return self._clock_event

    @property
    def events(self) -> dict:
        """Named events dict for event-driven simulation."""
        return {"step": self._clock_event}

    @property
    def current_time(self) -> float:
        """Current simulation time in seconds, delegated to Xyce."""
        return self._xyce.getSimTime()

    async def next_event(self, target_time: float = None, event_type: str = "step") -> str:
        """Advance simulation to *target_time* and return the fired event name.

        Runs ``setPauseTime`` + ``simulateUntil`` in an executor so the
        asyncio event loop is not blocked.  After simulation advances, ADC
        states are compared to the previous snapshot: if any state changed
        the method returns ``"threshold_crossed"``, otherwise ``"step"``.

        Raises :class:`ValueError` for unknown *event_type* values.
        """
        valid_types = {"step", "threshold_crossed"}
        if event_type not in valid_types:
            raise ValueError(
                f"Unknown event type '{event_type}'; expected one of {valid_types}"
            )

        if target_time is None:
            target_time = self._current_time + 1e-9

        loop = asyncio.get_running_loop()

        def _advance():
            self._xyce.setPauseTime(target_time)
            status, actual = self._xyce.simulateUntil(target_time)
            if status != 1:
                msg = ""
                if hasattr(self._xyce, "getLastError"):
                    msg = self._xyce.getLastError()
                raise RuntimeError(
                    f"Xyce simulateUntil failed at {target_time}: {msg}" if msg
                    else f"Xyce simulateUntil failed at {target_time} (status={status})"
                )
            self._current_time = actual

        await loop.run_in_executor(None, _advance)

        # Check for ADC state changes
        current_states = self.read_adc_states()

        # Populate YADC overrides: translate ADC states to quantized voltages
        if hasattr(self, "_yadc_to_node") and self._yadc_to_node:
            vdd = getattr(self, "_vdd", 1.8)
            for yadc_name, node_name in self._yadc_to_node.items():
                state = current_states.get(yadc_name)
                if state is not None:
                    self._yadc_overrides[node_name] = vdd if state >= 1 else 0.0

        if self._prev_adc_states and current_states != self._prev_adc_states:
            self._prev_adc_states = current_states
            return "threshold_crossed"

        self._prev_adc_states = current_states
        return "step"

    def get_signal_event(self, signal_name: str) -> asyncio.Event:
        return self._clock_event

    def read(self, variable_name: str) -> float:
        # Return YADC quantized voltage if available
        if hasattr(self, "_yadc_overrides") and variable_name in self._yadc_overrides:
            return self._yadc_overrides[variable_name]

        # Try the fast in-memory API first (works for some device params / Y-outputs)
        status, value = self._xyce.obtainResponse(variable_name)
        if status != 0:
            return value

        # Fall back to parsing the .prn file, which always contains node voltages
        prn_path = self._prn_path()
        if os.path.exists(prn_path):
            parser = XycePrnParser(prn_path)
            parser.parse()
            return parser.read_at_time(variable_name, self._current_time)

        raise KeyError(
            f"Xyce variable '{variable_name}' not found via obtainResponse "
            f"and no PRN output at {prn_path}"
        )

    def _prn_path(self) -> str:
        """Derive the expected PRN path from the netlist filename."""
        base = os.path.basename(self._netlist_path)
        # Xyce appends .prn to the netlist name, e.g. run.cir -> run.cir.prn
        return self._netlist_path + ".prn"

    def set_param(self, param_name: str, value: float) -> bool:
        status = self._xyce.setCircuitParameter(param_name, value)
        return status == 1

    # Aliases for mixed-signal bridge compatibility
    setCircuitParameter = set_param

    def update_dac(self, dac_name: str, time_array: list, voltage_array: list):
        # Xyce YDAC devices require the internal name format (YDAC!<name>)
        internal_name = dac_name if "!" in dac_name else f"YDAC!{dac_name}"
        self._xyce.updateTimeVoltagePairs(internal_name, time_array, voltage_array)

    updateTimeVoltagePairs = update_dac

    def simulateUntil(self, time: float):
        status, actual = self._xyce.simulateUntil(time)
        if status == 1:
            self._current_time = actual
        return status, actual

    def set_pause_time(self, pause_time: float) -> None:
        """Set a simulation pause time (synchronous breakpoint).

        Calls ``xyce_interface.setPauseTime`` and raises :class:`RuntimeError`
        if the call does not succeed.
        """
        result = self._xyce.setPauseTime(pause_time)
        if result != 1:
            msg = ""
            if hasattr(self._xyce, "getLastError"):
                msg = self._xyce.getLastError()
            raise RuntimeError(
                f"Xyce setPauseTime({pause_time}) failed: {msg}" if msg
                else f"Xyce setPauseTime({pause_time}) failed (result={result})"
            )

    def read_adc_states(self) -> dict:
        """Read the current state of all ADC devices.

        Calls ``xyce_interface.getTimeStatePairsADC`` and returns a
        ``{ADCname: latest_state}`` dictionary.  Returns an empty dict on
        error.
        """
        try:
            data = self._xyce.getTimeStatePairsADC()
            # data format: (names_tuple, pairs_for_adc0, pairs_for_adc1, ...)
            # Each pairs tuple contains (time, state) tuples.
            if not data or len(data) < 2:
                return {}
            names = data[0]
            result = {}
            for i, name in enumerate(names):
                pairs = data[i + 1] if (i + 1) < len(data) else ()
                # The latest state is the state from the last (time, state) pair
                if pairs:
                    result[name] = pairs[-1][-1]
                else:
                    result[name] = None
            return result
        except Exception as e:
            import logging
            logging.getLogger("toffee.xyce").warning(
                "Failed to read ADC states: %s", e
            )
            return {}

    def get_adc_map(self) -> tuple:
        """Return the ADC device map from ``xyce_interface.getADCMap``."""
        return self._xyce.getADCMap()

    def finish(self):
        self._xyce.close()
        if self._temp_dir:
            import shutil
            shutil.rmtree(self._temp_dir, ignore_errors=True)

    # ================================================================== #
    # AnalogBackend interface
    # ================================================================== #

    def set_source(self, name: str, value: float) -> None:
        """Set a constant voltage source (AnalogBackend contract).

        Xyce requires time-voltage pairs; we emit a 1 ns step waveform.
        """
        self.updateTimeVoltagePairs(
            name,
            [self._current_time, self._current_time + 1e-9],
            [value, value],
        )

    def set_source_waveform(self, name: str, times: list, values: list) -> None:
        """Set a time-varying voltage source (AnalogBackend contract)."""
        self.updateTimeVoltagePairs(name, times, values)

    # -- set_parameter delegates to setCircuitParameter --
    set_parameter = setCircuitParameter

    def register_trigger(self, node: str, threshold: float) -> None:
        """No-op: Xyce detects threshold crossings via PAUSE breakpoints
        in the C++ layer (``N_DEV_ADC.C``).  No Python-side trigger needed."""
        pass

    def unregister_trigger(self, node: str) -> None:
        """No-op: see :meth:`register_trigger`."""
        pass
