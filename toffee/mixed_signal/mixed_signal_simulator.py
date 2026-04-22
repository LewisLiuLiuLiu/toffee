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
    4. Reads analog OUT ports and maps them back to digital IN ports (ADC).
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
                self._apply_analog_to_digital()
        else:
            status, actual = self._analog.simulateUntil(time)
            if status != 1:
                raise RuntimeError(f"Analog simulator failed at {time}")
            self._current_time = actual
            self._apply_analog_to_digital()

    def _apply_digital_to_analog(self, until_time: float):
        for d_name, analog_name, scale, offset in self._mapping.iter_d2a():
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

        for d_name, param_name, code_mapping in self._mapping.iter_d2a_param():
            if self._mapping.get_digital_direction(d_name) != PortDirection.OUT:
                continue
            raw_val = getattr(self._dut, d_name, None)
            if raw_val is None:
                continue
            if raw_val not in code_mapping:
                raise ValueError(
                    f"Digital port '{d_name}' value {raw_val} not in d2a_param mapping"
                )
            param_value = code_mapping[raw_val]
            if hasattr(self._analog, "setCircuitParameter"):
                self._analog.setCircuitParameter(param_name, param_value)

    def _apply_analog_to_digital(self):
        """Read analog results and drive digital DUT pins.

        For Xyce backend: use YADC getTimeStatePairsADC() if yadc_device is specified.
        For ngspice backend (or fallback): use read() + Python threshold comparison.
        """
        # --- Xyce YADC batch read (if any a2d uses yadc_device) ---
        yadc_results = {}
        yadc_needed = any(
            yadc_device
            for _, _, _, _, yadc_device in self._mapping.iter_a2d()
        )
        if yadc_needed and hasattr(self._analog, '_xyce'):
            try:
                (status, ADCnames, numADCnames, numPoints,
                 timeArray, stateArray) = self._analog._xyce.getTimeStatePairsADC()
                if status == 1:
                    for i, name in enumerate(ADCnames):
                        if numPoints > 0:
                            yadc_results[name] = stateArray[i][numPoints - 1]
            except (RuntimeError, OSError, AttributeError) as exc:
                import logging
                logging.getLogger(__name__).debug(
                    "YADC getTimeStatePairsADC failed, falling back to threshold: %s", exc
                )

        # --- Per-port A2D ---
        for analog_name, d_name, threshold, invert, yadc_device in self._mapping.iter_a2d():
            if yadc_device and yadc_device in yadc_results:
                # Xyce YADC path: use quantized digital state directly
                digital_val = yadc_results[yadc_device]
            else:
                # ngspice / fallback path: read voltage + threshold
                voltage = self._analog.read(analog_name)
                digital_val = 1 if voltage >= threshold else 0

            if invert:
                digital_val = 0 if digital_val else 1

            pin = getattr(self._dut, d_name, None)
            if pin is None:
                continue
            if hasattr(pin, "value"):
                pin.value = digital_val
            else:
                setattr(self._dut, d_name, digital_val)

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
