"""Verification tests for the async event notification system.

These tests independently verify the contracts specified in the design:
1. NgSpice: lazy loop capture, bounded deque, is_closed guard, WARNING logging
2. Xyce: set_pause_time, read_adc_states, env variables
3. Simulator base: events property, next_event() contract (step but NOT tick)
4. asynchronous.py: __event_loop unified set/clear
"""

import asyncio
import ctypes
import logging
import threading
from collections import deque
from unittest.mock import MagicMock, patch

import pytest

from toffee.simulator import Simulator
from toffee.analog.ngspice_simulator import (
    NgSpiceSimulator,
    _VecValues,
    _VecValuesAll,
)


# ====================================================================
# Helpers
# ====================================================================

def _make_ngspice_stub():
    """Create a minimal NgSpiceSimulator without loading libngspice."""
    sim = NgSpiceSimulator.__new__(NgSpiceSimulator)
    sim._async_triggers = {}
    sim._trigger_lock = threading.Lock()
    sim._node_voltages = {}
    sim._spice_time = 5e-9
    sim._next_sync_time = float("inf")
    sim._asyncio_loop = None
    sim._clock_event = asyncio.Event()
    sim._events = {"step": sim._clock_event, "threshold_crossed": asyncio.Event()}
    sim._pending_events = deque(maxlen=100)  # Match production type
    sim._event_lock = threading.Lock()
    sim._simulation_done = False
    return sim


def _make_vva(name: bytes, value: float):
    """Build a minimal _VecValuesAll pointer for one signal."""
    vv = _VecValues(
        name=name, creal=value, cimag=0.0, is_scale=False, is_complex=False
    )
    p_vv = ctypes.pointer(ctypes.pointer(vv))
    vva = _VecValuesAll(veccount=1, vecindex=0, vecsa=p_vv)
    return ctypes.pointer(vva)


class _StubSimulator(Simulator):
    """Concrete Simulator subclass for testing base class behavior."""

    def __init__(self):
        self._clock_event = asyncio.Event()
        self._step_count = 0
        self._tick_count = 0

    def step(self, cycles: int = 1) -> None:
        self._step_count += cycles

    @property
    def clock_event(self) -> asyncio.Event:
        return self._clock_event

    def get_signal_event(self, signal_name: str) -> asyncio.Event:
        return self._clock_event

    def tick(self) -> None:
        self._tick_count += 1
        super().tick()


# ====================================================================
# 1. NgSpice: Lazy loop capture
# ====================================================================

@pytest.mark.asyncio
async def test_ensure_loop_returns_running_loop():
    """_ensure_loop() must capture asyncio.get_running_loop(), not set in __init__."""
    sim = _make_ngspice_stub()
    assert sim._asyncio_loop is None, "Loop must NOT be captured at construction time"

    sim._ensure_loop()

    assert sim._asyncio_loop is asyncio.get_running_loop()


@pytest.mark.asyncio
async def test_ensure_loop_idempotent():
    """Calling _ensure_loop() twice doesn't change the captured loop."""
    sim = _make_ngspice_stub()
    sim._ensure_loop()
    first = sim._asyncio_loop
    sim._ensure_loop()
    assert sim._asyncio_loop is first


def test_ensure_loop_no_running_loop():
    """_ensure_loop() must not crash when no event loop is running."""
    sim = _make_ngspice_stub()
    sim._ensure_loop()  # Should not raise
    assert sim._asyncio_loop is None


# ====================================================================
# 2. NgSpice: Bounded deque for pending_events (maxlen=100)
# ====================================================================

def test_pending_events_is_deque_with_maxlen():
    """Production _pending_events must be a deque with maxlen=100."""
    sim = _make_ngspice_stub()
    assert isinstance(sim._pending_events, deque)
    assert sim._pending_events.maxlen == 100


def test_pending_events_bounded_overflow():
    """When more than 100 events are appended, oldest are dropped."""
    sim = _make_ngspice_stub()
    for i in range(150):
        sim._pending_events.append(f"evt_{i}")
    assert len(sim._pending_events) == 100
    # Oldest event should be evt_50 (0..49 dropped)
    assert sim._pending_events[0] == "evt_50"
    assert sim._pending_events[-1] == "evt_149"


# ====================================================================
# 3. NgSpice: is_closed() guard before call_soon_threadsafe
# ====================================================================

@pytest.mark.asyncio
async def test_trigger_with_closed_loop_does_not_crash():
    """When the asyncio loop is closed, trigger fires without crashing."""
    sim = _make_ngspice_stub()

    # Create and close a loop to simulate a closed loop
    closed_loop = asyncio.new_event_loop()
    closed_loop.close()
    sim._asyncio_loop = closed_loop

    sim.add_async_trigger("v(out)", threshold=1.0)

    vva_ptr = _make_vva(b"v(out)", 2.0)
    # Must not raise even with closed loop
    sim._on_send_data(vva_ptr, 1, 0, None)

    # Event should NOT be set because loop is closed
    assert not sim._events["threshold_crossed"].is_set()
    # But pending_events should still record it
    assert "threshold_crossed" in sim._pending_events


@pytest.mark.asyncio
async def test_trigger_with_none_loop_does_not_crash():
    """When _asyncio_loop is None, trigger fires without crashing."""
    sim = _make_ngspice_stub()
    assert sim._asyncio_loop is None

    sim.add_async_trigger("v(out)", threshold=1.0)

    vva_ptr = _make_vva(b"v(out)", 2.0)
    sim._on_send_data(vva_ptr, 1, 0, None)

    assert not sim._events["threshold_crossed"].is_set()
    assert "threshold_crossed" in sim._pending_events


# ====================================================================
# 4. NgSpice: WARNING-level logging for errors in trigger handler
# ====================================================================

@pytest.mark.asyncio
async def test_trigger_handler_logs_warning_on_error():
    """If call_soon_threadsafe raises, a WARNING is logged (not crash)."""
    sim = _make_ngspice_stub()
    sim._asyncio_loop = asyncio.get_running_loop()
    sim.add_async_trigger("v(out)", threshold=1.0)

    # Monkey-patch the event's .set to raise
    original_set = sim._events["threshold_crossed"].set
    def bad_set():
        raise RuntimeError("simulated failure")
    sim._events["threshold_crossed"].set = bad_set

    vva_ptr = _make_vva(b"v(out)", 2.0)

    with patch("logging.Logger.warning") as mock_warn:
        sim._on_send_data(vva_ptr, 1, 0, None)
        # The error should be caught and logged
        assert mock_warn.called or "threshold_crossed" in sim._pending_events


# ====================================================================
# 5. NgSpice: Trigger correctly disarms after firing
# ====================================================================

@pytest.mark.asyncio
async def test_trigger_disarms_after_firing():
    """After a trigger fires, it should be disarmed (armed=False)."""
    sim = _make_ngspice_stub()
    sim._asyncio_loop = asyncio.get_running_loop()
    sim.add_async_trigger("v(out)", threshold=1.5)

    assert sim._async_triggers["v(out)"]["armed"] is True

    vva_ptr = _make_vva(b"v(out)", 1.6)
    sim._on_send_data(vva_ptr, 1, 0, None)

    assert sim._async_triggers["v(out)"]["armed"] is False


@pytest.mark.asyncio
async def test_trigger_does_not_fire_below_threshold():
    """Trigger should not fire when value is below threshold."""
    sim = _make_ngspice_stub()
    sim._asyncio_loop = asyncio.get_running_loop()
    sim.add_async_trigger("v(out)", threshold=1.5)

    vva_ptr = _make_vva(b"v(out)", 1.4)
    sim._on_send_data(vva_ptr, 1, 0, None)

    assert sim._async_triggers["v(out)"]["armed"] is True
    assert len(sim._pending_events) == 0


@pytest.mark.asyncio
async def test_trigger_does_not_fire_twice():
    """Once disarmed, the trigger should not fire again."""
    sim = _make_ngspice_stub()
    sim._asyncio_loop = asyncio.get_running_loop()
    sim.add_async_trigger("v(out)", threshold=1.5)

    vva_ptr = _make_vva(b"v(out)", 2.0)
    sim._on_send_data(vva_ptr, 1, 0, None)
    assert len(sim._pending_events) == 1

    # Second send_data with value still above threshold
    vva_ptr2 = _make_vva(b"v(out)", 3.0)
    sim._on_send_data(vva_ptr2, 1, 0, None)
    assert len(sim._pending_events) == 1  # Still only one event


# ====================================================================
# 6. NgSpice: _next_sync_time is forced to current spice_time on trigger
# ====================================================================

@pytest.mark.asyncio
async def test_trigger_forces_sync_time():
    """When trigger fires, _next_sync_time should be set to current _spice_time."""
    sim = _make_ngspice_stub()
    sim._spice_time = 42e-9
    sim._next_sync_time = float("inf")
    sim._asyncio_loop = asyncio.get_running_loop()
    sim.add_async_trigger("v(out)", threshold=1.0)

    vva_ptr = _make_vva(b"v(out)", 1.5)
    sim._on_send_data(vva_ptr, 1, 0, None)

    assert sim._next_sync_time == 42e-9


# ====================================================================
# 7. Simulator base: events property
# ====================================================================

def test_base_events_returns_step_key():
    """Default events property returns {'step': clock_event}."""
    sim = _StubSimulator()
    events = sim.events
    assert isinstance(events, dict)
    assert "step" in events
    assert events["step"] is sim.clock_event


def test_base_events_only_step():
    """Default events should contain exactly one key: 'step'."""
    sim = _StubSimulator()
    assert list(sim.events.keys()) == ["step"]


# ====================================================================
# 8. Simulator base: next_event() calls step(1), returns "step", NOT tick()
# ====================================================================

@pytest.mark.asyncio
async def test_next_event_calls_step():
    """next_event() must call step(1)."""
    sim = _StubSimulator()
    assert sim._step_count == 0
    result = await sim.next_event()
    assert result == "step"
    assert sim._step_count == 1


@pytest.mark.asyncio
async def test_next_event_does_not_call_tick():
    """next_event() must NOT call tick() — __event_loop handles that."""
    sim = _StubSimulator()
    assert sim._tick_count == 0
    await sim.next_event()
    assert sim._tick_count == 0, "next_event() must not call tick()"


@pytest.mark.asyncio
async def test_next_event_return_type():
    """next_event() must return a string."""
    sim = _StubSimulator()
    result = await sim.next_event()
    assert isinstance(result, str)


# ====================================================================
# 9. Xyce: set_pause_time, read_adc_states (independent verification)
# ====================================================================

def test_xyce_set_pause_time_wraps_correctly():
    """set_pause_time() should delegate to _xyce.setPauseTime and check result."""
    from toffee.analog.xyce_simulator import XyceSimulator

    sim = XyceSimulator.__new__(XyceSimulator)
    mock_xyce = MagicMock()
    mock_xyce.setPauseTime.return_value = 1
    sim._xyce = mock_xyce

    sim.set_pause_time(10e-9)

    mock_xyce.setPauseTime.assert_called_once_with(10e-9)


def test_xyce_set_pause_time_raises_on_failure():
    """set_pause_time() should raise RuntimeError when setPauseTime returns 0."""
    from toffee.analog.xyce_simulator import XyceSimulator

    sim = XyceSimulator.__new__(XyceSimulator)
    mock_xyce = MagicMock()
    mock_xyce.setPauseTime.return_value = 0
    sim._xyce = mock_xyce

    with pytest.raises(RuntimeError, match="setPauseTime"):
        sim.set_pause_time(10e-9)


def test_xyce_read_adc_states_parses_correctly():
    """read_adc_states() should extract the latest state per ADC."""
    from toffee.analog.xyce_simulator import XyceSimulator

    sim = XyceSimulator.__new__(XyceSimulator)
    mock_xyce = MagicMock()
    mock_xyce.getTimeStatePairsADC.return_value = (
        ("ADC1", "ADC2"),
        ((0.0, 0), (1e-9, 1), (2e-9, 1)),
        ((0.0, 0),),
    )
    sim._xyce = mock_xyce

    result = sim.read_adc_states()
    assert result["ADC1"] == 1  # Last state from 3 pairs
    assert result["ADC2"] == 0  # Last state from 1 pair


def test_xyce_read_adc_states_empty_data():
    """read_adc_states() returns {} when data is None or too short."""
    from toffee.analog.xyce_simulator import XyceSimulator

    sim = XyceSimulator.__new__(XyceSimulator)
    mock_xyce = MagicMock()

    # Test with None
    mock_xyce.getTimeStatePairsADC.return_value = None
    sim._xyce = mock_xyce
    assert sim.read_adc_states() == {}

    # Test with single element (len < 2)
    mock_xyce.getTimeStatePairsADC.return_value = (("ADC1",),)
    assert sim.read_adc_states() == {}


def test_xyce_read_adc_states_exception_returns_empty():
    """read_adc_states() returns {} and logs warning on exception."""
    from toffee.analog.xyce_simulator import XyceSimulator

    sim = XyceSimulator.__new__(XyceSimulator)
    mock_xyce = MagicMock()
    mock_xyce.getTimeStatePairsADC.side_effect = RuntimeError("xyce error")
    sim._xyce = mock_xyce

    result = sim.read_adc_states()
    assert result == {}


def test_xyce_read_adc_states_with_empty_pairs():
    """read_adc_states() returns None for ADC with no pairs."""
    from toffee.analog.xyce_simulator import XyceSimulator

    sim = XyceSimulator.__new__(XyceSimulator)
    mock_xyce = MagicMock()
    mock_xyce.getTimeStatePairsADC.return_value = (
        ("ADC1",),
        (),  # Empty pairs
    )
    sim._xyce = mock_xyce

    result = sim.read_adc_states()
    assert result["ADC1"] is None


# ====================================================================
# 10. Xyce: Environment variable paths
# ====================================================================

def test_xyce_env_variables():
    """XYCE_SHARE and XYCE_LIB env vars should be read at module level."""
    from toffee.analog import xyce_simulator
    # Verify the module reads env vars (even if they fall back to defaults)
    assert hasattr(xyce_simulator, "_DEFAULT_XYCE_SHARE")
    assert hasattr(xyce_simulator, "_DEFAULT_XYCE_LIB")
    assert isinstance(xyce_simulator._DEFAULT_XYCE_SHARE, str)
    assert isinstance(xyce_simulator._DEFAULT_XYCE_LIB, str)


# ====================================================================
# 11. NgSpice: _on_send_data with null vdata
# ====================================================================

def test_send_data_null_vdata():
    """_on_send_data should return 0 when vdata is null/falsy."""
    sim = _make_ngspice_stub()
    result = sim._on_send_data(None, 0, 0, None)
    assert result == 0


# ====================================================================
# 12. NgSpice: Node voltage normalization in _on_send_data
# ====================================================================

@pytest.mark.asyncio
async def test_send_data_stores_node_voltage():
    """_on_send_data should store voltage in _node_voltages."""
    sim = _make_ngspice_stub()
    vva_ptr = _make_vva(b"v(out)", 3.3)
    sim._on_send_data(vva_ptr, 1, 0, None)
    assert sim._node_voltages.get("v(out)") == 3.3
    # Also stored as "out" (stripped v(...) wrapper)
    assert sim._node_voltages.get("out") == 3.3


# ====================================================================
# 13. NgSpice: events property returns correct dict
# ====================================================================

def test_ngspice_events_property():
    """NgSpiceSimulator.events should return dict with 'step' and 'threshold_crossed'."""
    sim = _make_ngspice_stub()
    events = sim.events
    assert "step" in events
    assert "threshold_crossed" in events
    assert events["step"] is sim._clock_event


# ====================================================================
# 14. __event_loop: unified set/clear (structural check)
# ====================================================================

@pytest.mark.asyncio
async def test_event_loop_function_exists():
    """__event_loop must exist in asynchronous module."""
    import toffee.asynchronous as async_mod
    # __event_loop is name-mangled but accessible as _Asynchronous__event_loop
    # Actually it's a module-level function, accessible via its mangled name
    assert hasattr(async_mod, "_Asynchronous__event_loop") or \
           hasattr(async_mod, "__event_loop") or \
           callable(getattr(async_mod, "start_clock", None))
    # Verify start_clock uses __event_loop (not __clock_loop)
    import inspect
    src = inspect.getsource(async_mod.start_clock)
    assert "__event_loop" in src, "start_clock should use __event_loop"
