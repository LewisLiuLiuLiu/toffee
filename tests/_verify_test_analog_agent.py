"""Verification tests for AnalogAgent event configuration and backward compatibility."""
import asyncio
import logging
import pytest

from toffee.simulator import Simulator
from toffee.analog.analog_agent import AnalogAgent


class StubSimulator(Simulator):
    """Minimal Simulator subclass for testing."""

    def __init__(self):
        self._clock_event = asyncio.Event()
        self._step_count = 0

    def step(self, cycles: int = 1) -> None:
        self._step_count += cycles

    @property
    def clock_event(self) -> asyncio.Event:
        return self._clock_event

    def get_signal_event(self, signal_name: str) -> asyncio.Event:
        return self._clock_event


class EventfulSimulator(StubSimulator):
    """Simulator with additional named events."""

    def __init__(self):
        super().__init__()
        self._threshold_event = asyncio.Event()

    @property
    def events(self) -> dict:
        return {
            "step": self.clock_event,
            "threshold_crossed": self._threshold_event,
        }


# --- Test 1: AnalogAgent default event uses clock_event's wait ---

def test_analog_agent_default_event_uses_clock_wait():
    """AnalogAgent(simulator=sim) with default event_name='step' should use clock_event.wait as monitor_step."""
    sim = StubSimulator()
    agent = AnalogAgent(simulator=sim)
    # Bound methods are not identity-equal; compare the underlying object
    assert agent.monitor_step.__self__ is sim.clock_event
    assert agent.monitor_step.__func__ is sim.clock_event.wait.__func__
    assert agent._event_name == "step"
    assert agent.simulator is sim


# --- Test 2: AnalogAgent custom event uses the correct event ---

def test_analog_agent_custom_event_uses_correct_wait():
    """AnalogAgent with event_name='threshold_crossed' should use that event's wait."""
    sim = EventfulSimulator()
    agent = AnalogAgent(simulator=sim, event_name="threshold_crossed")
    assert agent.monitor_step.__self__ is sim._threshold_event
    assert agent._event_name == "threshold_crossed"


# --- Test 3: AnalogAgent fallback when event_name not found ---

def test_analog_agent_fallback_to_clock_event():
    """If event_name is not in events dict, should fallback to clock_event."""
    sim = StubSimulator()
    agent = AnalogAgent(simulator=sim, event_name="nonexistent")
    # Should fall back to clock_event
    assert agent.monitor_step.__self__ is sim.clock_event
    assert agent._event_name == "nonexistent"


# --- Test 4: AnalogAgent bundle path still works ---

def test_analog_agent_bundle_path():
    """AnalogAgent without simulator should work with bundle."""
    class MockBundle:
        def step(self):
            pass

    bundle = MockBundle()
    agent = AnalogAgent(bundle=bundle)
    assert agent.bundle is bundle
    assert agent.monitor_step.__self__ is bundle
    assert agent._event_name == "step"


# --- Test 5: AnalogAgent with simulator triggers deprecation warning ---

def test_analog_agent_simulator_emits_deprecation_warning(caplog):
    """AnalogAgent(simulator=sim) DOES emit a spurious deprecation warning.

    This documents a known issue: the Agent.__init__ path for callable
    arguments emits a warning intended for direct users, but AnalogAgent
    triggers it internally. Functional but noisy.
    """
    sim = StubSimulator()
    with caplog.at_level(logging.WARNING):
        agent = AnalogAgent(simulator=sim)
    deprecation_warnings = [
        r for r in caplog.records
        if "deprecated" in r.message.lower()
    ]
    # Confirm the warning IS emitted (this is the undesirable current behavior)
    assert len(deprecation_warnings) == 1, (
        f"Expected exactly 1 deprecation warning, got {len(deprecation_warnings)}"
    )
    # But the agent is still functional
    assert hasattr(agent, 'monitor_step')
    assert agent.simulator is sim


# --- Test 6: Simulator.events default has 'step' ---

def test_simulator_events_default():
    """Default events dict contains only 'step' -> clock_event."""
    sim = StubSimulator()
    assert "step" in sim.events
    assert sim.events["step"] is sim.clock_event


# --- Test 7: Simulator.next_event default implementation ---

@pytest.mark.asyncio
async def test_next_event_default():
    """Default next_event() calls step(1) and returns 'step'."""
    sim = StubSimulator()
    result = await sim.next_event()
    assert result == "step"
    assert sim._step_count == 1


# --- Test 8: next_event must not call tick ---

@pytest.mark.asyncio
async def test_next_event_does_not_call_tick():
    """Default next_event() must NOT call tick() -- __event_loop handles set/clear."""
    sim = StubSimulator()
    tick_called = False
    original_tick = sim.tick

    def spy_tick():
        nonlocal tick_called
        tick_called = True
        original_tick()

    sim.tick = spy_tick
    await sim.next_event()
    assert not tick_called, "next_event() must not call tick()"


# --- Test 9: start_clock backward compatibility with legacy DUTs ---

def test_start_clock_wraps_legacy_dut():
    """start_clock() should wrap a legacy DUT that doesn't have clock_event."""
    class LegacyDUT:
        """DUT object without clock_event attribute (old picker-style)."""
        def __init__(self):
            self.event = asyncio.Event()
            self.xclock = type('xclock', (), {'_step_event': self.event})()

        def Step(self, n):
            pass

    dut = LegacyDUT()
    assert not hasattr(dut, 'clock_event')
    # start_clock wraps it in DigitalSimulator which adds clock_event
    from toffee.digital_simulator import DigitalSimulator
    wrapped = DigitalSimulator(dut)
    assert hasattr(wrapped, 'clock_event')
    assert wrapped.clock_event is dut.event


# --- Test 10: __has_unwait_task skips __clock_loop named task ---

def test_event_loop_task_name_compat():
    """The __event_loop task should be named '__clock_loop' for __has_unwait_task() compatibility."""
    import inspect
    from toffee import asynchronous
    source = inspect.getsource(asynchronous.start_clock)
    assert '__clock_loop' in source, "start_clock must set task name to '__clock_loop'"


# --- Test 11: AnalogAgent with simulator does NOT have .bundle attribute ---

def test_analog_agent_simulator_path_no_bundle_attr():
    """When AnalogAgent uses the simulator path, .bundle should NOT be set (callable path)."""
    sim = StubSimulator()
    agent = AnalogAgent(simulator=sim)
    # The callable path in Agent.__init__ does NOT set self.bundle
    assert not hasattr(agent, 'bundle'), (
        "AnalogAgent with simulator should not have .bundle attribute"
    )
