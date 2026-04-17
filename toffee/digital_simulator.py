"""Digital simulator adapter for picker-generated DUTs."""

import asyncio
from .simulator import Simulator


class DigitalSimulator(Simulator):
    """Wrap a picker-generated DUT to conform to the Simulator interface."""

    def __init__(self, dut):
        self.dut = dut
        self._event = dut.event

    def step(self, cycles: int = 1) -> None:
        self.dut.Step(cycles)

    @property
    def clock_event(self) -> asyncio.Event:
        return self._event

    def get_signal_event(self, signal_name: str) -> asyncio.Event:
        """Return the XPin's event if available, otherwise fall back to clock_event."""
        xpin = getattr(self.dut, signal_name, None)
        if xpin is not None and hasattr(xpin, "event"):
            return xpin.event
        return self._event
