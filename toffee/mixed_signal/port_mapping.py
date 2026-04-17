from enum import Enum, auto
from dataclasses import dataclass
from typing import Dict, Tuple

__all__ = ["PortDirection", "BridgeSpec", "PortMapping"]


class PortDirection(Enum):
    IN = auto()
    OUT = auto()
    INOUT = auto()


@dataclass
class BridgeSpec:
    analog_name: str
    scale: float = 1.0
    offset: float = 0.0


class PortMapping:
    """Declarative map between digital DUT pins and analog SPICE nodes/params."""

    def __init__(self):
        self._digital: Dict[str, PortDirection] = {}
        self._analog: Dict[str, PortDirection] = {}
        self._bridges: Dict[str, BridgeSpec] = {}

    def add_digital(self, name: str, direction: PortDirection = PortDirection.INOUT) -> "PortMapping":
        self._digital[name] = direction
        return self

    def add_analog(self, name: str, direction: PortDirection = PortDirection.INOUT) -> "PortMapping":
        self._analog[name] = direction
        return self

    def bridge(self, digital_name: str, analog_name: str, scale: float = 1.0, offset: float = 0.0) -> "PortMapping":
        if digital_name not in self._digital:
            raise KeyError(f"Digital port '{digital_name}' not declared")
        if analog_name not in self._analog:
            raise KeyError(f"Analog port '{analog_name}' not declared")
        self._bridges[digital_name] = BridgeSpec(analog_name, scale, offset)
        return self

    def get_bridge(self, digital_name: str) -> Tuple[str, float, float]:
        if digital_name not in self._bridges:
            raise KeyError(f"Digital port '{digital_name}' has no bridge declared")
        spec = self._bridges[digital_name]
        return spec.analog_name, spec.scale, spec.offset

    @property
    def digital_ports(self):
        return list(self._digital.keys())

    @property
    def analog_ports(self):
        return list(self._analog.keys())

    @property
    def bridges(self):
        return {k: (v.analog_name, v.scale, v.offset) for k, v in self._bridges.items()}
