import pytest

from toffee.mixed_signal.port_mapping import PortMapping, PortDirection


def test_port_mapping_basic():
    pm = PortMapping()
    pm.add_digital("dac_ctrl", direction=PortDirection.OUT)
    pm.add_analog("v_dac", direction=PortDirection.IN)
    pm.bridge("dac_ctrl", "v_dac", scale=1.8)
    assert pm.get_bridge("dac_ctrl") == ("v_dac", 1.8, 0.0)


def test_bridge_requires_declared_ports():
    pm = PortMapping()
    with pytest.raises(KeyError):
        pm.bridge("missing_digital", "v_dac")
    pm.add_digital("dac_ctrl", PortDirection.OUT)
    with pytest.raises(KeyError):
        pm.bridge("dac_ctrl", "missing_analog")


def test_properties_and_defaults():
    pm = PortMapping()
    pm.add_digital("a").add_analog("b").bridge("a", "b")
    assert pm.digital_ports == ["a"]
    assert pm.analog_ports == ["b"]
    assert pm.bridges == {"a": ("b", 1.0, 0.0)}
    assert pm.get_bridge("a") == ("b", 1.0, 0.0)


def test_param_bridge_requires_declared_digital_port():
    pm = PortMapping()
    with pytest.raises(KeyError):
        pm.param_bridge("missing", "r_load", mapping={0: 1e3})
