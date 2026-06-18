"""MixedSignalBundle and DutPin for mixed-signal verification."""

from ..analog.analog_bundle import AnalogBundle


class DutPin:
    """Signal that reads/writes a digital DUT pin."""

    def __init__(self, pin_name: str, dut):
        self._pin_name = pin_name
        self._dut = dut

    @property
    def value(self):
        pin = getattr(self._dut, self._pin_name)
        return pin.value if hasattr(pin, "value") else pin

    @value.setter
    def value(self, v):
        pin = getattr(self._dut, self._pin_name)
        if hasattr(pin, "value"):
            pin.value = v
        else:
            setattr(self._dut, self._pin_name, v)


class MixedSignalBundle(AnalogBundle):
    """Bundle for mixed-signal: analog signals + digital DUT pins."""

    def __init__(self, simulator=None, dut=None):
        super().__init__(simulator)
        self._dut = dut

    def bind_dut_pin(self, name: str, pin_name: str) -> DutPin:
        """Bind a DUT pin to this bundle."""
        pin = DutPin(pin_name, self._dut)
        setattr(self, name, pin)
        return pin
