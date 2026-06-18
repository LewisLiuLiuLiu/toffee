"""Analog signal and bundle abstractions for toffee."""

from ..bundle import Bundle
from .analog_signal import AnalogStimulus, AnalogObservation


class AnalogSignal:
    """Continuous-valued signal with multi-perspective accessors."""

    def __init__(self, name: str, simulator, read_fn):
        self.name = name
        self._simulator = simulator
        self._read_fn = read_fn

    @property
    def event(self):
        """Expose the simulator's clock event so triggers can await it."""
        return self._simulator.clock_event

    @property
    def voltage(self) -> float:
        return self._read_fn(self.name)

    @property
    def digital(self) -> int:
        v = self.voltage
        # Simple CMOS threshold; can be made configurable later
        return 1 if v > 0.9 else 0

    @property
    def is_marginal(self) -> bool:
        v = self.voltage
        return 0.3 < v < 1.2


class AnalogBundle(Bundle):
    """Bundle for analog signals driven by a Simulator backend."""

    def __init__(self, simulator=None):
        super().__init__()
        self._simulator = simulator
        if simulator is not None:
            self.set_clock_event(simulator.clock_event)

    def bind_stimulus(self, name: str, node_name: str) -> AnalogStimulus:
        """Bind a writeable analog stimulus to a SPICE voltage source node."""
        signal = AnalogStimulus(node_name, self._simulator)
        setattr(self, name, signal)
        return signal

    def bind_observation(self, name: str, signal_name: str) -> AnalogObservation:
        """Bind a readable analog observation to a SPICE node/expression."""
        signal = AnalogObservation(signal_name, self._simulator)
        setattr(self, name, signal)
        return signal

    def bind_signal(self, name: str, read_fn=None):
        """Deprecated: use bind_observation instead."""
        if read_fn is None and self._simulator is not None:
            read_fn = self._simulator.read
        signal = AnalogSignal(name, self._simulator, read_fn)
        setattr(self, name, signal)
        return signal
