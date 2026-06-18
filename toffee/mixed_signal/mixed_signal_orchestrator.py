"""Event-driven mixed-signal orchestrator.

Analog leads, digital follows (analog-leading mode).
Implements Simulator ABC so that start_clock(orchestrator)
drives __event_loop.
"""

import asyncio

from ..simulator import Simulator
from .bridge import MixedSignalBridge
from .port_mapping import PortMapping


class MixedSignalOrchestrator(Simulator):
    """Orchestrates a digital DUT and an analog backend.

    On every next_event() when A2D bridges exist:
    1. Analog advances to next event (clock_edge or threshold_crossed).
    2. A2D bridge reads analog voltages, updates digital input pins.
    3. Digital advance: RefreshComb() for crossings, Step(1) for clock edges.
    4. D2A bridge reads digital output pins, sets analog sources/params.
    """

    def __init__(self, dut, analog: Simulator, mapping: PortMapping, step_strategy=None):
        self._dut = dut
        self._analog = analog
        self._mapping = mapping
        self._step_strategy = step_strategy
        self._event = asyncio.Event()
        self._current_time = 0.0
        self._clock_boundary = 1e-9
        self._registered_triggers: list[str] = []
        self._finished = False
        # Auto-register A2D ports as async triggers
        if mapping.has_a2d():
            for a_name, d_name, threshold, invert, yadc in mapping.iter_a2d():
                analog.register_trigger(a_name, threshold)
                self._registered_triggers.append(a_name)

    # ========== Simulator ABC ==========

    async def next_event(self) -> str:
        if self._finished:
            return "step"
        if self._mapping.has_a2d():
            # Analog leads — advance to clock boundary, may be interrupted by trigger
            event_type = await self._analog.next_event(target_time=self._clock_boundary)
            # Ngspice returns "step" — normalize to "clock_edge"
            if event_type == "step":
                event_type = "clock_edge"
            self._current_time = self._analog.current_time
            self._a2d()
            if event_type == "threshold_crossed":
                self._dut.RefreshComb()
                self._d2a()
                # clock boundary does NOT advance — same boundary on next call
            elif event_type == "clock_edge":
                self._dut.Step(1)
                self._d2a()
                self._clock_boundary += 1e-9
            else:
                raise ValueError(f"Unknown event kind: {event_type}")
        else:
            # Digital leads — no A2D, no crossing risk
            self._dut.Step(1)
            self._d2a()
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, self._analog.step_time, 1e-9)
            self._current_time = self._analog.current_time
            self._a2d()
        return "step"

    def advance_to(self, time: float) -> None:
        """Jump to *time*, bridging at sub-step boundaries if StepStrategy is set."""
        if time > self._current_time:
            self.step_time(time - self._current_time)

    def step(self, cycles: int = 1) -> None:
        for _ in range(cycles):
            self.step_time(1e-9)

    def step_time(self, dt: float) -> None:
        if self._mapping.has_a2d():
            target = self._current_time + dt
            if self._step_strategy is not None:
                for sub_time in self._step_strategy.iter_steps(self._current_time, target):
                    # Use the full remaining window for D2A so backends that need
                    # time-voltage pairs (e.g. Xyce) see one coherent waveform
                    # instead of many short consecutive windows that the device
                    # may fail to stitch together across value changes.
                    self._d2a(until_time=target)
                    self._analog.step_time(sub_time - self._current_time)
                    self._current_time = self._analog.current_time
                    self._a2d()
                    self._dut.RefreshComb()
            else:
                self._d2a(until_time=target)
                self._analog.step_time(dt)
                self._current_time = self._analog.current_time
                self._a2d()
                self._dut.RefreshComb()
        else:
            self._dut.Step(1)
            self._d2a()
            self._analog.step_time(dt)
            self._current_time = self._analog.current_time
            self._a2d()
        self.tick()

    @property
    def clock_event(self) -> asyncio.Event:
        return self._event

    def get_signal_event(self, signal_name: str) -> asyncio.Event:
        return self._event

    # ========== Lifecycle ==========

    def finish(self):
        self._finished = True
        # Remove all registered async triggers
        for node_name in self._registered_triggers:
            self._analog.unregister_trigger(node_name)
        self._registered_triggers.clear()
        self._analog.finish()

    # ========== Bridge (private) ==========

    def _a2d(self):
        MixedSignalBridge.a2d(self._analog, self._dut, self._mapping)

    def _d2a(self, until_time=None):
        MixedSignalBridge.d2a(
            self._analog, self._dut, self._mapping, self._current_time, until_time
        )
