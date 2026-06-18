"""Analog signal types for stimulus and observation."""


class AnalogStimulus:
    """Writeable analog signal that drives a voltage source.

    Setting :attr:`value` calls ``simulator.set_source(node_name, value)``.
    """

    def __init__(self, node_name: str, simulator):
        self._node = node_name
        self._sim = simulator
        self._value = None

    @property
    def value(self):
        return self._value

    @value.setter
    def value(self, v):
        self._sim.set_source(self._node, v)
        self._value = v


class AnalogObservation:
    """Readable analog signal that reads a SPICE node voltage or current.

    Reading :attr:`voltage` calls ``simulator.read(signal_name)``.
    Accepts any SPICE expression (``"v(vout)"``, ``"v(@m5[vdsat])"``,
    ``"i(@m1[id])"``).
    """

    def __init__(self, signal_name: str, simulator):
        self._signal = signal_name
        self._sim = simulator

    @property
    def voltage(self):
        return self._sim.read(self._signal)
