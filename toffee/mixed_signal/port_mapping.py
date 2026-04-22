from enum import Enum, auto
from dataclasses import dataclass
from typing import Dict, Tuple

__all__ = ["PortDirection", "D2ASpec", "D2AParamSpec", "A2DSpec", "PortMapping"]


class PortDirection(Enum):
    IN = auto()
    OUT = auto()
    INOUT = auto()


@dataclass
class D2ASpec:
    analog_name: str
    scale: float = 1.0
    offset: float = 0.0


@dataclass
class D2AParamSpec:
    param_name: str
    mapping: Dict  # digital_code -> param_value


@dataclass
class A2DSpec:
    digital_name: str
    threshold: float = 0.9
    invert: bool = False
    yadc_device: str = ""


class PortMapping:
    """Declarative map between digital DUT pins and analog SPICE nodes/params."""

    def __init__(self):
        self._digital: Dict[str, PortDirection] = {}
        self._analog: Dict[str, PortDirection] = {}
        self._d2a: Dict[str, D2ASpec] = {}
        self._d2a_param: Dict[str, D2AParamSpec] = {}
        self._a2d: Dict[str, A2DSpec] = {}

    def add_digital(self, name: str, direction: PortDirection = PortDirection.INOUT) -> "PortMapping":
        self._digital[name] = direction
        return self

    def add_analog(self, name: str, direction: PortDirection = PortDirection.INOUT) -> "PortMapping":
        self._analog[name] = direction
        return self

    def d2a(self, digital_name: str, analog_name: str, scale: float = 1.0, offset: float = 0.0) -> "PortMapping":
        if digital_name not in self._digital:
            raise KeyError(f"Digital port '{digital_name}' not declared")
        if analog_name not in self._analog:
            raise KeyError(f"Analog port '{analog_name}' not declared")
        self._d2a[digital_name] = D2ASpec(analog_name, scale, offset)
        return self

    def get_d2a(self, digital_name: str) -> Tuple[str, float, float]:
        if digital_name not in self._d2a:
            raise KeyError(f"Digital port '{digital_name}' has no d2a mapping declared")
        spec = self._d2a[digital_name]
        return spec.analog_name, spec.scale, spec.offset

    @property
    def digital_ports(self):
        return list(self._digital.keys())

    @property
    def analog_ports(self):
        return list(self._analog.keys())

    def get_digital_direction(self, name: str) -> PortDirection:
        return self._digital[name]

    def d2a_param(self, digital_name: str, param_name: str, mapping: dict) -> "PortMapping":
        if digital_name not in self._digital:
            raise KeyError(f"Digital port '{digital_name}' not declared")
        self._d2a_param[digital_name] = D2AParamSpec(param_name, mapping)
        return self

    def get_d2a_param(self, digital_name: str) -> Tuple[str, Dict]:
        if digital_name not in self._d2a_param:
            raise KeyError(f"Digital port '{digital_name}' has no d2a_param mapping declared")
        spec = self._d2a_param[digital_name]
        return spec.param_name, spec.mapping

    def iter_d2a(self):
        """Yield (digital_name, analog_name, scale, offset) for d2a mappings."""
        for d_name, spec in self._d2a.items():
            yield d_name, spec.analog_name, spec.scale, spec.offset

    def iter_d2a_param(self):
        """Yield (digital_name, param_name, code_mapping)."""
        for d_name, spec in self._d2a_param.items():
            yield d_name, spec.param_name, spec.mapping

    @property
    def d2a_map(self):
        return {k: (v.analog_name, v.scale, v.offset) for k, v in self._d2a.items()}

    def a2d(self, analog_name: str, digital_name: str, threshold: float = 0.9, invert: bool = False, yadc_device: str = "") -> "PortMapping":
        if analog_name not in self._analog:
            raise KeyError(f"Analog port '{analog_name}' not declared")
        if digital_name not in self._digital:
            raise KeyError(f"Digital port '{digital_name}' not declared")
        self._a2d[analog_name] = A2DSpec(digital_name, threshold, invert, yadc_device)
        return self

    def get_a2d(self, analog_name: str) -> Tuple[str, float, bool, str]:
        if analog_name not in self._a2d:
            raise KeyError(f"Analog port '{analog_name}' has no a2d mapping declared")
        spec = self._a2d[analog_name]
        return spec.digital_name, spec.threshold, spec.invert, spec.yadc_device

    def iter_a2d(self):
        """Yield (analog_name, digital_name, threshold, invert, yadc_device)."""
        for a_name, spec in self._a2d.items():
            yield a_name, spec.digital_name, spec.threshold, spec.invert, spec.yadc_device
