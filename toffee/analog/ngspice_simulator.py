"""Ngspice shared-library simulator backend for toffee Phase 1.

Uses ctypes to bind libngspice.so and implements lazy-sync co-simulation
via the GetSyncData callback.  Static analyses (.op/.dc/.ac) still work
via direct command execution.
"""

from __future__ import annotations

import asyncio
import ctypes
import ctypes.util
import os
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path

from ..simulator import Simulator
from .ngspice_raw_parser import NgSpiceRawParser


# --------------------------------------------------------------------------- #
# ctypes types derived from ngspice sharedspice.h (independent implementation)
# --------------------------------------------------------------------------- #

class _NgComplex(ctypes.Structure):
    _fields_ = [
        ("cx_real", ctypes.c_double),
        ("cx_imag", ctypes.c_double),
    ]


class _VecValues(ctypes.Structure):
    _fields_ = [
        ("name", ctypes.c_char_p),
        ("creal", ctypes.c_double),
        ("cimag", ctypes.c_double),
        ("is_scale", ctypes.c_bool),
        ("is_complex", ctypes.c_bool),
    ]


class _VecValuesAll(ctypes.Structure):
    _fields_ = [
        ("veccount", ctypes.c_int),
        ("vecindex", ctypes.c_int),
        ("vecsa", ctypes.POINTER(ctypes.POINTER(_VecValues))),
    ]


class _VectorInfo(ctypes.Structure):
    _fields_ = [
        ("v_name", ctypes.c_char_p),
        ("v_type", ctypes.c_int),
        ("v_flags", ctypes.c_short),
        ("v_realdata", ctypes.POINTER(ctypes.c_double)),
        ("v_compdata", ctypes.POINTER(_NgComplex)),
        ("v_length", ctypes.c_int),
    ]


# Callback signatures
_SEND_CHAR = ctypes.CFUNCTYPE(
    ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_void_p
)
_SEND_STAT = ctypes.CFUNCTYPE(
    ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_void_p
)
_CONTROLLED_EXIT = ctypes.CFUNCTYPE(
    ctypes.c_int, ctypes.c_int, ctypes.c_bool, ctypes.c_bool,
    ctypes.c_int, ctypes.c_void_p,
)
_SEND_DATA = ctypes.CFUNCTYPE(
    ctypes.c_int, ctypes.POINTER(_VecValuesAll), ctypes.c_int,
    ctypes.c_int, ctypes.c_void_p,
)
_SEND_INIT_DATA = ctypes.CFUNCTYPE(
    ctypes.c_int, ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p
)
_BG_THREAD_RUNNING = ctypes.CFUNCTYPE(
    ctypes.c_int, ctypes.c_bool, ctypes.c_int, ctypes.c_void_p
)
_GET_VSRC_DATA = ctypes.CFUNCTYPE(
    ctypes.c_int, ctypes.POINTER(ctypes.c_double), ctypes.c_double,
    ctypes.c_char_p, ctypes.c_int, ctypes.c_void_p,
)
_GET_ISRC_DATA = ctypes.CFUNCTYPE(
    ctypes.c_int, ctypes.POINTER(ctypes.c_double), ctypes.c_double,
    ctypes.c_char_p, ctypes.c_int, ctypes.c_void_p,
)
_GET_SYNC_DATA = ctypes.CFUNCTYPE(
    ctypes.c_int, ctypes.c_double, ctypes.POINTER(ctypes.c_double),
    ctypes.c_double, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    ctypes.c_void_p,
)


def _find_libngspice(lib_path: str | None = None) -> str:
    if lib_path is not None:
        p = Path(lib_path)
        if p.is_file():
            return str(p)
        if p.is_dir():
            for pattern in ("libngspice*.so*", "libngspice*.dylib*"):
                for candidate in sorted(p.glob(pattern)):
                    return str(candidate)
        raise FileNotFoundError(f"Cannot find libngspice at: {lib_path}")

    found = ctypes.util.find_library("ngspice")
    if found:
        return found

    raise FileNotFoundError(
        "Cannot find libngspice shared library. "
        "Install libngspice0-dev or pass lib_path explicitly."
    )


# Global registry for mapping userdata pointer -> simulator instance.
# This allows GetSyncData to be a plain module-level function, avoiding
# a performance / correctness issue with bound methods / local closures
# observed under pytest.
_simulators: dict[int, "NgSpiceSimulator"] = {}


def _on_get_sync_data_global(
    ckttime: float,
    p_delta: ctypes.POINTER(ctypes.c_double),
    old_delta: float,
    redostep: int,
    ident: int,
    location: int,
    userdata: int,
) -> int:
    sim = _simulators.get(userdata)
    if sim is None or sim._simulation_done:
        return 0
    time_to_sync = sim._next_sync_time - ckttime
    if time_to_sync <= 0:
        sim._spice_time = ckttime
        sim._sync_event.set()
        sim._resume_event.wait()
        sim._resume_event.clear()
        return 0
    if p_delta and p_delta[0] > time_to_sync:
        p_delta[0] = time_to_sync
    return 0


class NgSpiceSimulator(Simulator):
    """
    Phase 1 ngspice backend using ctypes + lazy sync.

    * Static analyses (.op/.dc/.ac) are run synchronously via
      ``ngSpice_Command("run")``.
    * Transient analyses (.tran) are started with ``bg_run`` and stepped
      lazily via the ``GetSyncData`` callback so that the Python event
      loop retains control.
    """

    def __init__(
        self,
        netlist_path: str,
        lib_path: str | None = None,
    ):
        self._netlist_path = netlist_path
        self._clock_event = asyncio.Event()
        self._current_time = 0.0
        self._results: dict[str, float | list] = {}
        self._temp_dir = tempfile.mkdtemp(prefix="toffee_ngspice_")

        # -- node voltages updated by SendData callback --
        self._node_voltages: dict[str, float] = {}
        self._spice_time = 0.0

        # -- external VSRC values --
        self._vsrc_values: dict[str, float] = {}
        self._vsrc_lock = threading.Lock()

        # -- lazy-sync threading primitives --
        self._sync_event = threading.Event()
        self._resume_event = threading.Event()
        self._next_sync_time = 0.0
        self._bg_running = False
        self._simulation_done = False
        self._last_error: RuntimeError | None = None

        # -- async analog triggers (experimental) --
        self._async_triggers: dict[str, dict] = {}
        self._trigger_lock = threading.Lock()

        # -- load shared library --
        resolved = _find_libngspice(lib_path)
        self._lib = ctypes.CDLL(resolved)
        self._setup_lib_signatures()

        # -- create and keep references to callbacks (avoid GC) --
        self._cb_send_char = _SEND_CHAR(self._on_send_char)
        self._cb_send_stat = _SEND_STAT(self._on_send_stat)
        self._cb_controlled_exit = _CONTROLLED_EXIT(self._on_controlled_exit)
        self._cb_send_data = _SEND_DATA(self._on_send_data)
        self._cb_send_init_data = _SEND_INIT_DATA(self._on_send_init_data)
        self._cb_bg_thread_running = _BG_THREAD_RUNNING(self._on_bg_thread_running)
        self._cb_get_vsrc_data = _GET_VSRC_DATA(self._on_get_vsrc_data)
        self._cb_get_isrc_data = _GET_ISRC_DATA(self._on_get_isrc_data)
        self._cb_get_sync_data = _GET_SYNC_DATA(_on_get_sync_data_global)

        self._user_id = id(self)
        _simulators[self._user_id] = self
        self._userdata = ctypes.c_void_p(self._user_id)

        ident = ctypes.c_int(0)
        self._lib.ngSpice_Init(
            self._cb_send_char,
            self._cb_send_stat,
            self._cb_controlled_exit,
            self._cb_send_data,
            self._cb_send_init_data,
            self._cb_bg_thread_running,
            self._userdata,
        )
        self._lib.ngSpice_Init_Sync(
            self._cb_get_vsrc_data,
            self._cb_get_isrc_data,
            self._cb_get_sync_data,
            ctypes.byref(ident),
            self._userdata,
        )

    def add_async_trigger(self, node_name: str, threshold: float):
        """Arm an analog trigger that fires when *node_name* >= *threshold*."""
        with self._trigger_lock:
            self._async_triggers[node_name] = {"threshold": threshold, "armed": True}

    def remove_async_trigger(self, node_name: str):
        with self._trigger_lock:
            self._async_triggers.pop(node_name, None)

    # ------------------------------------------------------------------ #
    # Library setup
    # ------------------------------------------------------------------ #
    def _setup_lib_signatures(self) -> None:
        # ngSpice_Init and ngSpice_Init_Sync signatures are required so that
        # ctypes correctly converts the CFUNCTYPE callback objects to C pointers.
        self._lib.ngSpice_Init.argtypes = [
            _SEND_CHAR, _SEND_STAT, _CONTROLLED_EXIT,
            _SEND_DATA, _SEND_INIT_DATA, _BG_THREAD_RUNNING,
            ctypes.c_void_p,
        ]
        self._lib.ngSpice_Init.restype = ctypes.c_int

        self._lib.ngSpice_Init_Sync.argtypes = [
            _GET_VSRC_DATA, _GET_ISRC_DATA, _GET_SYNC_DATA,
            ctypes.POINTER(ctypes.c_int), ctypes.c_void_p,
        ]
        self._lib.ngSpice_Init_Sync.restype = ctypes.c_int

        self._lib.ngSpice_Command.argtypes = [ctypes.c_char_p]
        self._lib.ngSpice_Command.restype = ctypes.c_int

        self._lib.ngSpice_Circ.argtypes = [ctypes.POINTER(ctypes.c_char_p)]
        self._lib.ngSpice_Circ.restype = ctypes.c_int

        self._lib.ngGet_Vec_Info.argtypes = [ctypes.c_char_p]
        self._lib.ngGet_Vec_Info.restype = ctypes.POINTER(_VectorInfo)

        self._lib.ngSpice_CurPlot.argtypes = []
        self._lib.ngSpice_CurPlot.restype = ctypes.c_char_p

        self._lib.ngSpice_running.argtypes = []
        self._lib.ngSpice_running.restype = ctypes.c_bool

        self._lib.ngSpice_Reset.argtypes = []
        self._lib.ngSpice_Reset.restype = ctypes.c_int

    # ------------------------------------------------------------------ #
    # Callbacks
    # ------------------------------------------------------------------ #
    def _on_send_char(self, msg: bytes, ident: int, userdata: object) -> int:
        # Keep quiet to avoid GIL contention with the bg thread under pytest.
        return 0

    def _on_send_stat(self, msg: bytes, ident: int, userdata: object) -> int:
        return 0

    def _on_controlled_exit(
        self,
        exit_status: int,
        immediate: bool,
        quit_exit: bool,
        ident: int,
        userdata: object,
    ) -> int:
        if not quit_exit and exit_status != 0:
            self._last_error = RuntimeError(
                f"ngspice controlled exit with status {exit_status}"
            )
        self._simulation_done = True
        self._sync_event.set()
        self._resume_event.set()
        return 0

    def _on_send_data(
        self,
        vdata: ctypes.POINTER(_VecValuesAll),
        count: int,
        ident: int,
        userdata: object,
    ) -> int:
        if not vdata:
            return 0
        vva = vdata.contents
        for i in range(vva.veccount):
            vv = vva.vecsa[i].contents
            raw = vv.name.decode("utf-8", errors="replace") if vv.name else ""
            if not raw:
                continue
            if vv.is_scale:
                self._spice_time = vv.creal
                continue
            self._node_voltages[raw] = vv.creal
            # normalized aliases
            if "." in raw:
                short = raw.split(".", 1)[1]
                self._node_voltages[short] = vv.creal
                raw = short
            if raw.startswith("v(") and raw.endswith(")"):
                self._node_voltages[raw[2:-1]] = vv.creal
        try:
            with self._trigger_lock:
                for node, spec in self._async_triggers.items():
                    if not spec["armed"]:
                        continue
                    val = self._node_voltages.get(node)
                    if val is not None and val >= spec["threshold"]:
                        spec["armed"] = False
                        # Force the next GetSyncData call to pause immediately
                        self._next_sync_time = self._spice_time
        except Exception:
            # Swallow errors in C callback context to avoid crashing the interpreter
            pass
        return 0

    def _on_send_init_data(
        self, vdata: object, ident: int, userdata: object
    ) -> int:
        return 0

    def _on_bg_thread_running(
        self, running: bool, ident: int, userdata: object
    ) -> int:
        if not running:
            self._bg_running = False
            self._simulation_done = True
            self._sync_event.set()
            self._resume_event.set()
        return 0

    def _on_get_vsrc_data(
        self,
        p_value: ctypes.POINTER(ctypes.c_double),
        time: float,
        name: bytes,
        ident: int,
        userdata: object,
    ) -> int:
        src_name = name.decode("utf-8", errors="replace") if name else ""
        with self._vsrc_lock:
            value = self._vsrc_values.get(src_name)
            if value is None:
                value = self._vsrc_values.get(src_name.lower(), 0.0)
        if p_value:
            p_value[0] = float(value)
        return 0

    def _on_get_isrc_data(
        self,
        p_value: ctypes.POINTER(ctypes.c_double),
        time: float,
        name: bytes,
        ident: int,
        userdata: object,
    ) -> int:
        if p_value:
            p_value[0] = 0.0
        return 0

    # ------------------------------------------------------------------ #
    # Simulator ABC implementation
    # ------------------------------------------------------------------ #
    @property
    def clock_event(self) -> asyncio.Event:
        return self._clock_event

    def tick(self) -> None:
        event = self._clock_event
        event.set()
        event.clear()

    def get_signal_event(self, signal_name: str) -> asyncio.Event:
        return self._clock_event

    def step(self, cycles: int = 1) -> None:
        self.step_time(1e-9 * cycles)

    def advance_to(self, time: float) -> None:
        if time > self._current_time:
            self.step_time(time - self._current_time)

    def step_time(self, dt: float) -> None:
        """Advance ngspice to *current_time + dt* using lazy sync."""
        if not self._bg_running:
            # Start a background transient simulation on first step.
            self._start_lazy_transient()

        target = self._current_time + dt
        self._next_sync_time = target
        self._sync_event.clear()
        self._resume_event.set()          # let bg thread proceed
        if not self._sync_event.wait(timeout=60.0):
            raise RuntimeError(
                "Timeout waiting for ngspice to reach sync point "
                f"{target} s (current spice time {self._spice_time} s)"
            )
        self._current_time = self._spice_time
        self.tick()

    def _start_lazy_transient(self) -> None:
        """Load a long transient netlist and start bg_run for lazy sync."""
        self._node_voltages.clear()
        self._current_time = 0.0
        self._reset_sync_state()
        self._next_sync_time = 0.0        # stop immediately at t=0

        # For lazy sync we do NOT insert a .control block;
        # bg_run itself starts the transient analysis.
        with open(self._netlist_path, "r") as fh:
            original_lines = fh.readlines()

        merged: list[str] = []
        end_written = False
        for line in original_lines:
            stripped = line.strip().lower()
            if stripped == ".end":
                merged.append(".save all\n")
                merged.append(".tran 1n 1\n")
                merged.append(".end\n")
                end_written = True
                break
            else:
                merged.append(line)
        if not end_written:
            merged.append(".save all\n")
            merged.append(".tran 1n 1\n")
            merged.append(".end\n")

        self._load_netlist_lines(merged)

        ret = self._lib.ngSpice_Command(b"bg_run")
        _ = self._lib.ngSpice_running()   # yield GIL so the detach thread can start
        if ret != 0:
            raise RuntimeError(f"ngSpice bg_run failed with code {ret}")
        self._bg_running = True
        # Wait for ngspice to reach the initial sync point at t=0.
        if not self._sync_event.wait(timeout=10.0):
            raise RuntimeError(
                "Timeout waiting for ngspice to reach initial sync point"
            )
        self._sync_event.clear()

    # ------------------------------------------------------------------ #
    # Circuit loading & analysis
    # ------------------------------------------------------------------ #
    def _load_netlist_lines(self, lines: list[str]) -> None:
        c_lines = (ctypes.c_char_p * (len(lines) + 1))()
        for i, line in enumerate(lines):
            c_lines[i] = line.encode("utf-8")
        c_lines[len(lines)] = None
        ret = self._lib.ngSpice_Circ(c_lines)
        if ret != 0:
            raise RuntimeError(f"ngSpice_Circ failed with code {ret}")

    def _load_circuit_for_analysis(
        self,
        analysis_cmds: list[str],
        save_vars: list[str] | None = None,
        raw_path: str | None = None,
    ) -> None:
        with open(self._netlist_path, "r") as fh:
            original_lines = fh.readlines()

        merged: list[str] = []
        end_written = False
        for line in original_lines:
            stripped = line.strip().lower()
            if stripped == ".end":
                if save_vars:
                    merged.append(".save all\n")
                    for var in save_vars:
                        merged.append(f".save {var}\n")
                merged.extend(self._control_block_lines(analysis_cmds, raw_path))
                merged.append(".end\n")
                end_written = True
                break
            else:
                merged.append(line)
        if not end_written:
            if save_vars:
                merged.append(".save all\n")
                for var in save_vars:
                    merged.append(f".save {var}\n")
            merged.extend(self._control_block_lines(analysis_cmds, raw_path))
            merged.append(".end\n")

        self._load_netlist_lines(merged)

    def _control_block_lines(self, analysis_cmds: list[str], raw_path: str | None = None) -> list[str]:
        lines = []
        for cmd in analysis_cmds:
            lines.append(f"{cmd}\n")
        lines.append(".control\n")
        lines.append("run\n")
        if raw_path:
            lines.append(f"write {raw_path}\n")
        lines.append(".endc\n")
        return lines

    def run_analysis(
        self,
        analysis_cmds: list[str],
        save_vars: list[str] | None = None,
    ) -> dict:
        """
        Run a ngspice analysis.

        * If *analysis_cmds* contains ``.tran``, a background transient
          simulation is started and the method returns immediately.
        * Otherwise the analysis is run synchronously and the resulting
          data dictionary is returned.
        """
        # Determine if this is a transient analysis.
        is_transient = any(
            cmd.strip().lower().startswith(".tran") for cmd in analysis_cmds
        )

        raw_name = "run.raw"
        raw_path = os.path.join(self._temp_dir, raw_name)

        self._load_circuit_for_analysis(analysis_cmds, save_vars, raw_path)

        if is_transient:
            self._reset_sync_state()
            ret = self._lib.ngSpice_Command(b"bg_run")
            if ret != 0:
                raise RuntimeError(f"ngSpice bg_run failed with code {ret}")
            self._bg_running = True
            # For API compatibility, block until the simulation finishes.
            # (Users who want lazy stepping should call step_time() directly.)
            self._wait_bg_done()
            self._results = dict(self._node_voltages)
            return self._results

        # Synchronous static analysis.
        ret = self._lib.ngSpice_Command(b"run")
        if ret != 0:
            raise RuntimeError(f"ngSpice run failed with code {ret}")

        # Prefer raw-file parsing for static analyses because it contains
        # all variables (including independent source voltages) reliably.
        parser = NgSpiceRawParser(raw_path)
        self._results = parser.parse()
        # Also merge live callback data as a supplement.
        self._results.update(self._node_voltages)
        return self._results

    def _reset_sync_state(self) -> None:
        self._sync_event.clear()
        self._resume_event.clear()
        self._next_sync_time = float("inf")
        self._simulation_done = False
        self._last_error = None

    def _wait_bg_done(self) -> None:
        """Block until the background thread signals completion."""
        while self._lib.ngSpice_running():
            self._sync_event.wait(timeout=0.1)
            self._sync_event.clear()
            if self._last_error is not None:
                raise self._last_error
        if self._last_error is not None:
            raise self._last_error

    # ------------------------------------------------------------------ #
    # External source control
    # ------------------------------------------------------------------ #
    def set_vsrc(self, name: str, voltage: float) -> None:
        """Set the value of an EXTERNAL voltage source."""
        with self._vsrc_lock:
            self._vsrc_values[name] = float(voltage)

    # ------------------------------------------------------------------ #
    # Data access
    # ------------------------------------------------------------------ #
    def read(self, variable_name: str) -> float | list:
        keys = self._normalize_name(variable_name)
        for key in keys:
            if key in self._node_voltages:
                return self._node_voltages[key]
            if key in self._results:
                return self._results[key]
        raise KeyError(
            f"Variable '{variable_name}' (tried {keys}) not found. "
            f"Available: {list(self._node_voltages.keys()) + list(self._results.keys())}"
        )

    @staticmethod
    def _normalize_name(name: str) -> list[str]:
        """Return candidate lookup keys for a variable name."""
        lowered = name.lower().strip()
        candidates = [lowered]

        # Strip plot prefix, e.g. "tran1.v(vout)" -> "v(vout)"
        if "." in lowered:
            short = lowered.split(".", 1)[1]
            if short not in candidates:
                candidates.append(short)

        # Strip v()/i() wrapper, e.g. "v(vout)" -> "vout"
        for prefix in ("v(", "i("):
            if lowered.startswith(prefix) and lowered.endswith(")"):
                bare = lowered[len(prefix) : -1]
                if bare not in candidates:
                    candidates.append(bare)

        return candidates

    # ------------------------------------------------------------------ #
    # Lifecycle
    # ------------------------------------------------------------------ #
    def finish(self) -> None:
        self._simulation_done = True
        # Prevent the bg thread from re-blocking in GetSyncData at the old
        # sync point so that bg_halt's ft_intrpt flag is checked promptly.
        self._next_sync_time = float("inf")
        self._resume_event.set()
        self._sync_event.set()
        import time
        time.sleep(0.1)
        # Always halt if ngspice reports it is running, even if our local
        # _bg_running flag has been cleared by the bg-thread-exited callback.
        # This avoids a race where the detach thread is still winding down
        # (e.g. holding triggerMutex) while the next test calls ngSpice_Init.
        for _ in range(5):
            try:
                ret = self._lib.ngSpice_Command(b"bg_halt")
            except Exception:
                ret = -1
            if ret == 0 and not self._lib.ngSpice_running():
                break
            time.sleep(0.5)
        self._bg_running = False
        # Use reset (not quit) to clear ngspice state.  'quit' triggers
        # shared_exit -> longjmp which can corrupt Python's ctypes frame
        # and break subsequent callback registrations in the same process.
        try:
            self._lib.ngSpice_Command(b"reset")
        except Exception:
            pass
        _simulators.pop(self._user_id, None)
        shutil.rmtree(self._temp_dir, ignore_errors=True)
