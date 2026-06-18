"""Tests for NgSpiceSimulator.next_event() target_time parameter.

These tests mock internal state (_current_time, _sync_event, etc.)
and do NOT depend on a real libngspice.so installation.
"""

import asyncio
import threading
from collections import deque
import pytest

from toffee.analog.ngspice_simulator import NgSpiceSimulator


def _make_stub_sim(current_time: float = 0.0) -> NgSpiceSimulator:
    """Create a stub NgSpiceSimulator with mocked internals for unit testing."""
    sim = NgSpiceSimulator.__new__(NgSpiceSimulator)
    sim._current_time = current_time
    sim._spice_time = current_time
    sim._bg_running = True
    sim._sync_event = threading.Event()
    sim._resume_event = threading.Event()
    sim._next_sync_time = float("inf")
    sim._simulation_done = False
    sim._last_error = None
    sim._asyncio_loop = None
    sim._pending_events = deque(maxlen=100)
    sim._event_lock = threading.Lock()
    sim._events = {"step": asyncio.Event(), "threshold_crossed": asyncio.Event()}
    sim._node_voltages = {}
    sim._clock_event = asyncio.Event()
    return sim


# ---------------------------------------------------------------------------
# RED: test that next_event accepts target_time and uses it
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_next_event_with_target_time_advances_to_target():
    """next_event(target_time=5e-9) should set _next_sync_time to 5e-9
    and update _current_time to the spice time after sync."""
    sim = _make_stub_sim(current_time=0.0)

    # We patch _start_lazy_transient so it's not called, and we simulate
    # the sync callback: when _resume_event is set, ngspice's bg thread
    # would eventually set _sync_event.  We simulate that by spawning a
    # helper thread that waits for _resume_event and then sets
    # _sync_event + updates _spice_time.
    def fake_bg_thread_response():
        sim._resume_event.wait(timeout=5.0)
        # Simulate ngspice reaching the target time
        sim._spice_time = sim._next_sync_time
        sim._sync_event.set()

    responder = threading.Thread(target=fake_bg_thread_response, daemon=True)
    responder.start()

    result = await sim.next_event(target_time=5e-9)

    responder.join(timeout=5.0)

    assert sim._current_time == pytest.approx(5e-9), (
        f"Expected _current_time=5e-9, got {sim._current_time}"
    )
    assert result == "step"


@pytest.mark.asyncio
async def test_next_event_without_target_time_uses_default_step():
    """next_event() without target_time should advance by 1e-9 (existing behavior)."""
    sim = _make_stub_sim(current_time=2e-9)

    def fake_bg_thread_response():
        sim._resume_event.wait(timeout=5.0)
        sim._spice_time = sim._next_sync_time
        sim._sync_event.set()

    responder = threading.Thread(target=fake_bg_thread_response, daemon=True)
    responder.start()

    result = await sim.next_event()

    responder.join(timeout=5.0)

    # Default behavior: current_time + 1e-9 = 2e-9 + 1e-9 = 3e-9
    assert sim._current_time == pytest.approx(3e-9), (
        f"Expected _current_time=3e-9, got {sim._current_time}"
    )
    assert result == "step"


@pytest.mark.asyncio
async def test_next_event_target_time_returns_threshold_crossed():
    """When a trigger fires during next_event(target_time=...),
    the pending event 'threshold_crossed' should be returned."""
    sim = _make_stub_sim(current_time=0.0)

    def fake_bg_thread_response():
        sim._resume_event.wait(timeout=5.0)
        sim._spice_time = 3e-9  # trigger fired at 3ns before reaching target
        # Simulate trigger adding pending event
        with sim._event_lock:
            sim._pending_events.append("threshold_crossed")
        sim._sync_event.set()

    responder = threading.Thread(target=fake_bg_thread_response, daemon=True)
    responder.start()

    result = await sim.next_event(target_time=5e-9)

    responder.join(timeout=5.0)

    assert result == "threshold_crossed"
