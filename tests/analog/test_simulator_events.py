"""Tests for Simulator base class events interface and AnalogAgent event config."""
import asyncio
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


# --- Simulator base class tests ---

def test_simulator_events_default():
    """Default events dict contains only 'step' -> clock_event."""
    sim = StubSimulator()
    assert "step" in sim.events
    assert sim.events["step"] is sim.clock_event


def test_simulator_events_override():
    """Subclass can override events to expose more named events."""
    sim = EventfulSimulator()
    assert "step" in sim.events
    assert "threshold_crossed" in sim.events
    assert sim.events["threshold_crossed"] is sim._threshold_event


@pytest.mark.asyncio
async def test_next_event_default():
    """Default next_event() calls step(1) and returns 'step'."""
    sim = StubSimulator()
    result = await sim.next_event()
    assert result == "step"
    assert sim._step_count == 1


@pytest.mark.asyncio
async def test_next_event_does_not_tick():
    """next_event() must NOT call tick() -- __event_loop handles set/clear."""
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


# --- AnalogAgent tests ---

def test_analog_agent_default_event():
    """AnalogAgent with default event_name='step' uses clock_event."""
    sim = StubSimulator()
    agent = AnalogAgent(simulator=sim)
    assert agent.simulator is sim
    assert agent._event_name == "step"


def test_analog_agent_custom_event():
    """AnalogAgent with event_name='threshold_crossed' uses that event."""
    sim = EventfulSimulator()
    agent = AnalogAgent(simulator=sim, event_name="threshold_crossed")
    assert agent._event_name == "threshold_crossed"


def test_analog_agent_fallback_to_clock_event():
    """If event_name not in events dict, fallback to clock_event."""
    sim = StubSimulator()
    agent = AnalogAgent(simulator=sim, event_name="nonexistent")
    assert agent._event_name == "nonexistent"
    # Should still initialize without error (falls back to clock_event)


def test_analog_agent_bundle_path():
    """AnalogAgent without simulator still works with bundle and stores event_name."""
    # Agent.__init__ needs a bundle with a .step attribute
    class MockBundle:
        def step(self):
            pass

    agent = AnalogAgent(bundle=MockBundle())
    assert agent._event_name == "step"
