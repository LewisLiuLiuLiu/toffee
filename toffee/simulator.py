"""Simulator abstraction layer for toffee.

This module defines the Simulator interface, which abstracts the time advancement
and event notification mechanisms for both digital (picker/Verilator) and analog
(ngspice/Xyce) backends.
"""

import asyncio
from abc import ABC, abstractmethod


class Simulator(ABC):
    """Abstract base class for simulation time drivers.

    Both digital DUTs (picker-generated) and analog SPICE engines implement
    this interface, allowing toffee's async event loop to remain agnostic
    to the underlying simulation backend.
    """

    @abstractmethod
    def step(self, cycles: int = 1) -> None:
        """Advance simulation time.

        For digital backends this is typically one clock cycle (dut.Step).
        For analog backends ``step(cycles)`` is a convenience wrapper that
        advances by ``cycles * 1 ns``; use :meth:`step_time` when you want
        an explicit time delta in seconds.
        """
        pass

    def step_time(self, dt: float) -> None:
        """Advance simulation time by *dt* seconds.

        Analog backends should implement this with the solver's native
        time-stepping API.  Digital backends that are cycle-based may
        raise :exc:`NotImplementedError`.
        """
        raise NotImplementedError(
            "step_time is not supported by this simulator backend"
        )

    @property
    @abstractmethod
    def clock_event(self) -> asyncio.Event:
        """Return the asyncio.Event that is set/cleared on every step()."""
        pass

    def tick(self) -> None:
        """Notify all waiters that a time step has completed."""
        event = self.clock_event
        event.set()
        event.clear()

    @abstractmethod
    def get_signal_event(self, signal_name: str) -> asyncio.Event:
        """Return the per-signal event used by triggers.

        For digital signals this may be the XPin's own event.
        For analog signals this usually falls back to clock_event.
        """
        pass
