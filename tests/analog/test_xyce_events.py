"""Tests for XyceSimulator event-driven interface: events, current_time, next_event.

All tests use a FakeXyceInterface (mock) -- no real Xyce library required.
"""

import asyncio
from unittest.mock import MagicMock

import pytest
import toffee_test
from toffee.analog.xyce_simulator import XyceSimulator


class FakeXyceInterface:
    """Minimal fake xyce_interface for testing XyceSimulator methods."""

    def __init__(self, libdir=None):
        self._libdir = libdir
        self._sim_time = 0.0

    def initialize(self, args):
        return 1

    def getSimTime(self):
        return self._sim_time

    def setPauseTime(self, pause_time):
        return 1

    def simulateUntil(self, time):
        self._sim_time = time
        return (1, time)

    def getTimeStatePairsADC(self):
        return (
            ("ADC1", "ADC2"),
            ((0.0, 0), (1e-9, 1)),
            ((0.0, 0), (1e-9, 0)),
        )

    def getADCMap(self):
        return (("ADC1", 0), ("ADC2", 1))

    def close(self):
        pass


def _make_sim():
    """Create an XyceSimulator stub backed by a FakeXyceInterface.

    Uses __new__() to bypass __init__ (which calls xyce_interface() and
    initialize()) so that no real Xyce library is needed.
    """
    sim = XyceSimulator.__new__(XyceSimulator)
    sim._xyce = FakeXyceInterface()
    sim._clock_event = asyncio.Event()
    sim._current_time = 0.0
    sim._prev_adc_states = {}
    sim._original_netlist = ""
    sim._netlist_path = ""
    sim._temp_dir = None
    return sim


# ---------------------------------------------------------------------------
# events property
# ---------------------------------------------------------------------------


@toffee_test.testcase
async def test_events_contains_step_key():
    """events dict must contain 'step' key mapped to clock_event.

    XyceSimulator should override the events property (not just inherit
    the base-class default) so that the mapping is explicit.
    """
    sim = _make_sim()
    # Verify via the class MRO that XyceSimulator defines its own events
    assert "events" in XyceSimulator.__dict__, (
        "XyceSimulator must override the 'events' property"
    )
    events = sim.events
    assert "step" in events
    assert events["step"] is sim._clock_event


# ---------------------------------------------------------------------------
# current_time property
# ---------------------------------------------------------------------------


@toffee_test.testcase
async def test_current_time_delegates_to_getSimTime():
    """current_time should delegate to _xyce.getSimTime()."""
    sim = _make_sim()
    sim._xyce._sim_time = 5.5e-9
    assert sim.current_time == 5.5e-9


@toffee_test.testcase
async def test_current_time_returns_zero_initially():
    """current_time should return 0.0 when simulation has not advanced."""
    sim = _make_sim()
    assert sim.current_time == 0.0


# ---------------------------------------------------------------------------
# next_event() -- no state change returns "step"
# ---------------------------------------------------------------------------


@toffee_test.testcase
async def test_next_event_returns_step_when_no_state_change():
    """next_event() should return 'step' when ADC states have not changed."""
    sim = _make_sim()
    # No previous ADC states stored, and current read returns states --
    # first call always stores states and returns "step" (no previous to compare).
    result = await sim.next_event(target_time=1e-9)
    assert result == "step"


# ---------------------------------------------------------------------------
# next_event() -- state change returns "threshold_crossed"
# ---------------------------------------------------------------------------


@toffee_test.testcase
async def test_next_event_returns_threshold_crossed_on_state_change():
    """next_event() should return 'threshold_crossed' when ADC state changes."""
    sim = _make_sim()

    # First call: stores initial ADC states, returns "step"
    result1 = await sim.next_event(target_time=1e-9)
    assert result1 == "step"

    # Now change ADC states for the second call
    # ADC1 changes from 1 -> 0, ADC2 stays 0
    sim._xyce.getTimeStatePairsADC = MagicMock(return_value=(
        ("ADC1", "ADC2"),
        ((0.0, 0), (2e-9, 0)),   # ADC1 state changed from 1 to 0
        ((0.0, 0), (2e-9, 0)),   # ADC2 unchanged
    ))

    result2 = await sim.next_event(target_time=2e-9)
    assert result2 == "threshold_crossed"


# ---------------------------------------------------------------------------
# next_event() runs simulateUntil in executor (non-blocking)
# ---------------------------------------------------------------------------


@toffee_test.testcase
async def test_next_event_runs_simulate_until_in_executor():
    """next_event() should run simulateUntil in an executor, not blocking the event loop."""
    sim = _make_sim()

    # Track whether simulateUntil was called
    original_simulate = sim._xyce.simulateUntil
    call_log = []

    def tracking_simulate_until(t):
        call_log.append(("simulateUntil", t))
        return original_simulate(t)

    sim._xyce.simulateUntil = tracking_simulate_until
    # Also track setPauseTime
    pause_log = []
    original_pause = sim._xyce.setPauseTime

    def tracking_set_pause(t):
        pause_log.append(("setPauseTime", t))
        return original_pause(t)

    sim._xyce.setPauseTime = tracking_set_pause

    result = await sim.next_event(target_time=5e-9)

    # setPauseTime must have been called before simulateUntil
    assert len(pause_log) == 1
    assert pause_log[0][1] == 5e-9
    assert len(call_log) == 1
    assert call_log[0][1] == 5e-9

    # The result should be "step" (no state change on first call)
    assert result == "step"


# ---------------------------------------------------------------------------
# next_event() with unknown event_type raises ValueError
# ---------------------------------------------------------------------------


@toffee_test.testcase
async def test_next_event_raises_on_unknown_event_type():
    """next_event() should raise ValueError when given an unknown event_type."""
    sim = _make_sim()
    with pytest.raises(ValueError, match="Unknown event type"):
        await sim.next_event(target_time=1e-9, event_type="unknown_event")
