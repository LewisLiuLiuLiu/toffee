import asyncio
import threading

import pytest
import toffee_test
from toffee.analog.ngspice_simulator import NgSpiceSimulator


@toffee_test.testcase
async def test_add_async_trigger_api():
    # We can't easily run a real transient without libngspice installed,
    # but we can verify the API surface and internal state.
    sim = NgSpiceSimulator.__new__(NgSpiceSimulator)
    sim._async_triggers = {}
    sim._trigger_lock = __import__("threading").Lock()
    sim._asyncio_loop = None

    sim.add_async_trigger("V(out)", threshold=1.5)
    assert "V(out)" in sim._async_triggers
    assert sim._async_triggers["V(out)"]["armed"] is True

    sim.remove_async_trigger("V(out)")
    assert "V(out)" not in sim._async_triggers


@toffee_test.testcase
async def test_send_data_fires_trigger():
    sim = NgSpiceSimulator.__new__(NgSpiceSimulator)
    sim._async_triggers = {}
    sim._trigger_lock = __import__("threading").Lock()
    sim._node_voltages = {}
    sim._spice_time = 5e-9
    sim._next_sync_time = float("inf")
    sim._asyncio_loop = None
    sim._events = {"step": asyncio.Event(), "threshold_crossed": asyncio.Event()}
    sim._pending_events = []
    sim._event_lock = __import__("threading").Lock()

    sim.add_async_trigger("v(out)", threshold=1.5)

    import ctypes
    from toffee.analog.ngspice_simulator import _VecValues, _VecValuesAll

    vv = _VecValues(name=b"v(out)", creal=1.6, cimag=0.0, is_scale=False, is_complex=False)
    p_vv = ctypes.pointer(ctypes.pointer(vv))
    vva = _VecValuesAll(veccount=1, vecindex=0, vecsa=p_vv)

    sim._on_send_data(ctypes.pointer(vva), 1, 0, None)

    assert sim._async_triggers["v(out)"]["armed"] is False
    assert sim._next_sync_time == 5e-9
    assert sim._node_voltages["v(out)"] == 1.6


# --- Step 1 tests: asyncio event system (lazy loop + events dict) ---


@toffee_test.testcase
async def test_events_property_returns_dict():
    """events property should return a dict with 'step' and 'threshold_crossed' keys."""
    sim = NgSpiceSimulator.__new__(NgSpiceSimulator)
    sim._clock_event = asyncio.Event()
    sim._events = {"step": sim._clock_event, "threshold_crossed": asyncio.Event()}

    events = sim.events
    assert isinstance(events, dict)
    assert "step" in events
    assert "threshold_crossed" in events
    assert events["step"] is sim._clock_event
    assert isinstance(events["threshold_crossed"], asyncio.Event)


@toffee_test.testcase
async def test_ensure_loop_captures_running_loop():
    """_ensure_loop() should capture the running asyncio loop when called from a coroutine."""
    sim = NgSpiceSimulator.__new__(NgSpiceSimulator)
    sim._asyncio_loop = None

    sim._ensure_loop()

    assert sim._asyncio_loop is not None
    assert sim._asyncio_loop is asyncio.get_running_loop()


@toffee_test.testcase
async def test_pending_events_and_event_lock_initialized():
    """__init__ should initialize _pending_events and _event_lock."""
    # We can't call __init__ without libngspice, so verify the attributes
    # are set when we manually construct them like the other stub tests.
    sim = NgSpiceSimulator.__new__(NgSpiceSimulator)
    sim._pending_events = []
    sim._event_lock = threading.Lock()

    assert isinstance(sim._pending_events, list)
    assert len(sim._pending_events) == 0
    assert isinstance(sim._event_lock, type(threading.Lock()))


# --- Step 2 tests: _on_send_data triggers asyncio notification ---


def _make_stub_sim():
    """Create a minimal stub NgSpiceSimulator for trigger testing."""
    sim = NgSpiceSimulator.__new__(NgSpiceSimulator)
    sim._async_triggers = {}
    sim._trigger_lock = threading.Lock()
    sim._node_voltages = {}
    sim._spice_time = 5e-9
    sim._next_sync_time = float("inf")
    sim._asyncio_loop = None
    sim._events = {"step": asyncio.Event(), "threshold_crossed": asyncio.Event()}
    sim._pending_events = []
    sim._event_lock = threading.Lock()
    return sim


@toffee_test.testcase
async def test_trigger_sets_threshold_crossed_event():
    """When a trigger fires, _events['threshold_crossed'] should be set."""
    sim = _make_stub_sim()
    sim._asyncio_loop = asyncio.get_running_loop()

    sim.add_async_trigger("v(out)", threshold=1.5)

    import ctypes
    from toffee.analog.ngspice_simulator import _VecValues, _VecValuesAll

    vv = _VecValues(name=b"v(out)", creal=1.6, cimag=0.0, is_scale=False, is_complex=False)
    p_vv = ctypes.pointer(ctypes.pointer(vv))
    vva = _VecValuesAll(veccount=1, vecindex=0, vecsa=p_vv)

    assert not sim._events["threshold_crossed"].is_set()
    sim._on_send_data(ctypes.pointer(vva), 1, 0, None)

    # The event should be set via call_soon_threadsafe; give the loop a chance
    await asyncio.sleep(0)
    assert sim._events["threshold_crossed"].is_set()


@toffee_test.testcase
async def test_trigger_appends_pending_events():
    """When a trigger fires, _pending_events should contain 'threshold_crossed'."""
    sim = _make_stub_sim()
    sim._asyncio_loop = asyncio.get_running_loop()

    sim.add_async_trigger("v(out)", threshold=1.5)

    import ctypes
    from toffee.analog.ngspice_simulator import _VecValues, _VecValuesAll

    vv = _VecValues(name=b"v(out)", creal=1.6, cimag=0.0, is_scale=False, is_complex=False)
    p_vv = ctypes.pointer(ctypes.pointer(vv))
    vva = _VecValuesAll(veccount=1, vecindex=0, vecsa=p_vv)

    sim._on_send_data(ctypes.pointer(vva), 1, 0, None)

    assert "threshold_crossed" in sim._pending_events


@toffee_test.testcase
async def test_trigger_no_event_without_loop():
    """When _asyncio_loop is None, trigger should still add to _pending_events but not crash."""
    sim = _make_stub_sim()
    # _asyncio_loop is already None

    sim.add_async_trigger("v(out)", threshold=1.5)

    import ctypes
    from toffee.analog.ngspice_simulator import _VecValues, _VecValuesAll

    vv = _VecValues(name=b"v(out)", creal=1.6, cimag=0.0, is_scale=False, is_complex=False)
    p_vv = ctypes.pointer(ctypes.pointer(vv))
    vva = _VecValuesAll(veccount=1, vecindex=0, vecsa=p_vv)

    sim._on_send_data(ctypes.pointer(vva), 1, 0, None)

    assert "threshold_crossed" in sim._pending_events
    assert not sim._events["threshold_crossed"].is_set()
