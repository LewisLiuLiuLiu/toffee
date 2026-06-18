"""Unit tests for DigitalSimulator."""

import asyncio

from toffee.digital_simulator import DigitalSimulator


class MockDut:
    """Minimal picker-like DUT with Step() and event attributes."""

    def __init__(self):
        self.step_count = 0
        self.event = asyncio.Event()

    def Step(self, cycles: int = 1):
        self.step_count += cycles


def test_events_property_has_step_key():
    """DigitalSimulator.events dict must contain 'step' mapping to clock_event."""
    dut = MockDut()
    sim = DigitalSimulator(dut)
    assert "step" in sim.events
    assert sim.events["step"] is sim.clock_event
