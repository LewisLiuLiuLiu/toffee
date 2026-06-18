"""Tests for AnalogAgent compare_func wiring and driver workflow."""
import asyncio
import pytest

from toffee.agent import Agent, driver_method
from toffee.analog.analog_agent import AnalogAgent
from toffee.analog.analog_bundle import AnalogBundle
from toffee._compare import tolerance_compare


class MockSim:
    def __init__(self):
        self.clock_event = asyncio.Event()
        self.events = {"step": self.clock_event}
        self.sources = {}
        self._read_val = 0.0
        self._time = 0.0

    def set_source(self, name, value):
        self.sources[name] = value

    def read(self, name):
        return self._read_val

    @property
    def current_time(self):
        return self._time

    def step_time(self, dt):
        self._time += dt
        self.clock_event.set()
        self.clock_event.clear()


class TestAnalogAgentDriverWorkflow:
    """End-to-end: Agent writes stimulus, steps, returns observation."""

    @pytest.mark.asyncio
    async def test_driver_method_writes_stimulus_and_returns_observation(self):
        sim = MockSim()
        bundle = AnalogBundle(sim)
        bundle.bind_stimulus("vinn", "VINN")
        bundle.bind_observation("vout", "v(vout)")

        sim._read_val = 1.23

        class OpampAgent(AnalogAgent):
            @driver_method()
            async def measure(self, vin_val):
                self.bundle.vinn.value = vin_val
                sim.step_time(1e-9)
                return self.bundle.vout.voltage

        agent = OpampAgent(bundle)
        result = await agent.measure(1.8)
        assert sim.sources["VINN"] == 1.8
        assert result == 1.23, f"Expected 1.23, got {result}"

    def test_compare_func_wired_to_driver(self):
        """Agent's compare_func must be set on all Driver objects."""
        sim = MockSim()
        bundle = AnalogBundle(sim)
        bundle.bind_stimulus("vinn", "VINN")

        cmp = tolerance_compare(0.05)

        class MyAgent(AnalogAgent):
            @driver_method()
            async def stim(self, v):
                pass

        agent = MyAgent(bundle, compare_func=cmp)
        driver = agent.drivers["stim"]
        assert driver.compare_func is cmp
