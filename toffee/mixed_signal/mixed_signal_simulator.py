import asyncio
from typing import Any

from ..simulator import Simulator
from .port_mapping import PortMapping, PortDirection


class MixedSignalSimulator(Simulator):
    """Orchestrates a digital DUT and an analog Xyce backend.

    On every advance_to():
    1. Reads digital OUT ports from the DUT.
    2. Maps them to analog IN ports (DAC voltages or circuit parameters).
    3. Advances the analog simulator to the target time.
    """

    def __init__(self, analog_simulator, dut, port_mapping: PortMapping, step_strategy=None):
        self._analog = analog_simulator
        self._dut = dut
        self._mapping = port_mapping
        self._step_strategy = step_strategy
        self._clock_event = asyncio.Event()
        self._current_time = 0.0

    def step_time(self, dt: float) -> None:
        if dt <= 0:
            raise ValueError(f"step_time requires positive dt, got {dt}")
        requested = self._current_time + dt
        self.advance_to(requested)
        self.tick()

    def step(self, cycles: int = 1) -> None:
        self.step_time(1e-9 * cycles)

    def advance_to(self, time: float) -> None:
        if time <= self._current_time:
            return
        self._apply_digital_to_analog(time)
        if self._step_strategy is not None:
            for sub_time in self._step_strategy.iter_steps(self._current_time, time):
                status, actual = self._analog.simulateUntil(sub_time)
                if status != 1:
                    raise RuntimeError(f"Analog simulator failed at {sub_time}")
                self._current_time = actual
        else:
            status, actual = self._analog.simulateUntil(time)
            if status != 1:
                raise RuntimeError(f"Analog simulator failed at {time}")
            self._current_time = actual

    def _apply_digital_to_analog(self, until_time: float):
        for d_name, analog_name, scale, offset in self._mapping.iter_voltage_bridges():
            if self._mapping.get_digital_direction(d_name) != PortDirection.OUT:
                continue
            raw_val = getattr(self._dut, d_name, None)
            if raw_val is None:
                continue
            analog_value = raw_val * scale + offset
            if hasattr(self._analog, "updateTimeVoltagePairs"):
                self._analog.updateTimeVoltagePairs(
                    analog_name,
                    [self._current_time, until_time],
                    [analog_value, analog_value],
                )

        for d_name, param_name, code_mapping in self._mapping.iter_param_bridges():
            raw_val = getattr(self._dut, d_name, None)
            if raw_val is None:
                continue
            if raw_val not in code_mapping:
                raise ValueError(
                    f"Digital port '{d_name}' value {raw_val} not in param bridge mapping"
                )
            param_value = code_mapping[raw_val]
            if hasattr(self._analog, "setCircuitParameter"):
                self._analog.setCircuitParameter(param_name, param_value)

    @property
    def clock_event(self) -> asyncio.Event:
        return self._clock_event

    def get_signal_event(self, signal_name: str) -> asyncio.Event:
        return self._clock_event

    def read(self, variable_name: str) -> float:
        return self._analog.read(variable_name)

    def finish(self):
        if hasattr(self._analog, "finish"):
            self._analog.finish()
