"""Shared D2A/A2D bridge logic for mixed-signal simulators.

Used by MixedSignalOrchestrator in both event-driven and lockstep modes.
"""

from .port_mapping import PortDirection


class MixedSignalBridge:
    """Stateless bridge between digital DUT pins and analog backend.

    Both D2A and A2D methods are static — the bridge owns no state.
    All necessary context (analog backend, DUT, PortMapping, time)
    is passed explicitly.
    """

    @staticmethod
    def d2a(analog, dut, mapping, current_time, until_time=None):
        """Push digital output pin values to analog sources and parameters.

        Args:
            analog: Analog backend (ngspice or Xyce).
            dut: Digital DUT object.
            mapping: PortMapping with D2A declarations.
            current_time: Current simulation time in seconds.
            until_time: Target time for waveform endpoints.  Defaults to
                ``current_time + 1e-9``.
        """
        if until_time is None:
            until_time = current_time + 1e-9

        for d_name, a_name, scale, offset in mapping.iter_d2a():
            if mapping.get_digital_direction(d_name) != PortDirection.OUT:
                continue
            pin = getattr(dut, d_name, None)
            if pin is None:
                continue
            raw = pin.value if hasattr(pin, "value") else pin
            analog_value = raw * scale + offset
            # Always provide an explicit time window when the backend supports
            # waveform sources.  Xyce needs the window to match the orchestrator's
            # current_time (its own _current_time may be stale in the sync path);
            # ngspice only supports instantaneous updates and will raise
            # NotImplementedError, so we fall back to set_source().
            try:
                analog.set_source_waveform(
                    a_name,
                    [current_time, until_time],
                    [analog_value, analog_value],
                )
            except NotImplementedError:
                analog.set_source(a_name, analog_value)

        for d_name, param_name, code_map in mapping.iter_d2a_param():
            if mapping.get_digital_direction(d_name) != PortDirection.OUT:
                continue
            pin = getattr(dut, d_name, None)
            if pin is None:
                continue
            raw = pin.value if hasattr(pin, "value") else pin
            if raw not in code_map:
                continue
            analog.set_parameter(param_name, code_map[raw])

    @staticmethod
    def a2d(analog, dut, mapping, yadc_results=None):
        """Read analog voltages and update digital input pins.

        Args:
            analog: Analog backend.
            dut: Digital DUT object.
            mapping: PortMapping with A2D declarations.
            yadc_results: Optional dict of ``{yadc_device_name: state}``.
                When provided, YADC-tagged ports use the quantized digital
                state directly instead of threshold comparison (used by
                lockstep advance_to path).
        """
        yadc_results = yadc_results or {}

        for a_name, d_name, threshold, invert, yadc_device in mapping.iter_a2d():
            if yadc_device and yadc_device in yadc_results:
                digital_val = yadc_results[yadc_device]
            else:
                voltage = analog.read(a_name)
                digital_val = 1 if voltage >= threshold else 0

            if invert:
                digital_val = 0 if digital_val else 1

            pin = getattr(dut, d_name, None)
            if pin is None:
                continue
            if hasattr(pin, "value"):
                pin.value = digital_val
            else:
                setattr(dut, d_name, digital_val)
