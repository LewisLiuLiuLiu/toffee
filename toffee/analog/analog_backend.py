"""AnalogBackend — interface for analog data interaction.

Separate from ``Simulator`` (time progression).  Only the two analog
backends (NgSpiceSimulator, XyceSimulator) implement this interface.
The orchestrator uses this interface for data; see ``MixedSignalBridge``.
"""

from abc import ABC, abstractmethod


class AnalogBackend(ABC):
    """Data interaction interface for analog simulators.

    Implementations: :class:`NgSpiceSimulator`, :class:`XyceSimulator`.
    """

    @abstractmethod
    def set_source(self, name: str, value: float) -> None:
        """Set an analog voltage source to a constant *value*."""
        ...

    def set_source_waveform(self, name: str, times: list, values: list) -> None:
        """Set an analog voltage source to a time-varying waveform.

        Default raises :exc:`NotImplementedError` — backends that only
        support constant sources (e.g. ngspice) should not override this.
        """
        raise NotImplementedError(
            f"{type(self).__name__} does not support set_source_waveform"
        )

    @abstractmethod
    def set_parameter(self, name: str, value: float) -> None:
        """Set a SPICE circuit parameter."""
        ...

    @abstractmethod
    def read(self, variable_name: str) -> float:
        """Read an analog node voltage."""
        ...

    def read_adc_states(self) -> dict:
        """Read the current state of all ADC devices.

        Returns ``{device_name: state}``.  Backends without ADC devices
        return an empty dict.
        """
        return {}

    @abstractmethod
    def register_trigger(self, node: str, threshold: float) -> None:
        """Register a threshold-crossing trigger on *node*."""
        ...

    @abstractmethod
    def unregister_trigger(self, node: str) -> None:
        """Remove a previously registered trigger."""
        ...

    @abstractmethod
    def finish(self) -> None:
        """Release backend resources."""
        ...
