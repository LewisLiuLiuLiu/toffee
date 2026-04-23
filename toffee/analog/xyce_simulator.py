"""Xyce shared-library simulator backend for toffee."""

import asyncio
import os
import sys
import tempfile

from ..simulator import Simulator
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


class XyceSimulator(Simulator):
    """
    Xyce backend using the official ctypes-based Python interface.

    This backend supports true step-by-step simulation via
    ``simulateUntil()``, enabling lazy synchronization in mixed-signal
    environments.
    """

    def __init__(self, netlist_path: str, libdir: str = None, analysis_cmds: list = None):
        self._original_netlist = netlist_path
        if libdir is None:
            libdir = _DEFAULT_XYCE_LIB
        self._xyce = xyce_interface(libdir=libdir)
        self._clock_event = asyncio.Event()
        self._current_time = 0.0

        # Xyce requires analysis commands in the netlist at initialization time.
        # If the caller provides them, create a temporary merged netlist.
        if analysis_cmds:
            self._temp_dir = tempfile.mkdtemp(prefix="toffee_xyce_")
            netlist_path = self._merge_netlist(netlist_path, analysis_cmds)
            self._netlist_path = netlist_path
        else:
            self._temp_dir = None
            self._netlist_path = netlist_path

        status = self._xyce.initialize([netlist_path])
        if status != 1:
            raise RuntimeError(
                f"Xyce initialize failed for {netlist_path} (status={status})"
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

    def step_time(self, dt: float) -> None:
        """Advance simulation by *dt* seconds."""
        requested = self._current_time + dt
        self.advance_to(requested)
        self.tick()

    def step(self, cycles: int = 1) -> None:
        """Convenience wrapper: advance by ``cycles * 1 ns``."""
        self.step_time(1e-9 * cycles)

    def advance_to(self, time: float) -> None:
        """Lazy synchronization: advance Xyce to *time* only if behind."""
        if time > self._current_time:
            status, actual = self._xyce.simulateUntil(time)
            if status != 1:
                raise RuntimeError(
                    f"Xyce simulateUntil failed at {time} (status={status})"
                )
            self._current_time = actual

    @property
    def clock_event(self) -> asyncio.Event:
        return self._clock_event

    def get_signal_event(self, signal_name: str) -> asyncio.Event:
        return self._clock_event

    def read(self, variable_name: str) -> float:
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

    # Aliases expected by MixedSignalSimulator
    setCircuitParameter = set_param

    def update_dac(self, dac_name: str, time_array: list, voltage_array: list):
        self._xyce.updateTimeVoltagePairs(dac_name, time_array, voltage_array)

    updateTimeVoltagePairs = update_dac

    def simulateUntil(self, time: float):
        return self._xyce.simulateUntil(time)

    def set_pause_time(self, pause_time: float) -> None:
        """Set a simulation pause time (synchronous breakpoint).

        Calls ``xyce_interface.setPauseTime`` and raises :class:`RuntimeError`
        if the call does not succeed.
        """
        result = self._xyce.setPauseTime(pause_time)
        if result != 1:
            raise RuntimeError(
                f"Xyce setPauseTime({pause_time}) failed (result={result})"
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
