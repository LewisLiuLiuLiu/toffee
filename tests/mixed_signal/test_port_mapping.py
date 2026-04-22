import pytest
import toffee_test

from toffee.mixed_signal.port_mapping import PortMapping, PortDirection, D2ASpec, D2AParamSpec, A2DSpec


@toffee_test.testcase
async def test_d2a_basic():
    pm = PortMapping()
    pm.add_digital("dac_ctrl", direction=PortDirection.OUT)
    pm.add_analog("v_dac", direction=PortDirection.IN)
    pm.d2a("dac_ctrl", "v_dac", scale=1.8)
    assert pm.get_d2a("dac_ctrl") == ("v_dac", 1.8, 0.0)


@toffee_test.testcase
async def test_d2a_requires_declared_ports():
    pm = PortMapping()
    with pytest.raises(KeyError):
        pm.d2a("missing_digital", "v_dac")
    pm.add_digital("dac_ctrl", PortDirection.OUT)
    with pytest.raises(KeyError):
        pm.d2a("dac_ctrl", "missing_analog")


@toffee_test.testcase
async def test_properties_and_defaults():
    pm = PortMapping()
    pm.add_digital("a").add_analog("b").d2a("a", "b")
    assert pm.digital_ports == ["a"]
    assert pm.analog_ports == ["b"]
    assert pm.d2a_map == {"a": ("b", 1.0, 0.0)}
    assert pm.get_d2a("a") == ("b", 1.0, 0.0)


@toffee_test.testcase
async def test_d2a_param_requires_declared_digital_port():
    pm = PortMapping()
    with pytest.raises(KeyError):
        pm.d2a_param("missing", "r_load", mapping={0: 1e3})


@toffee_test.testcase
async def test_a2d_basic():
    """Test a2d declaration and get_a2d retrieval."""
    pm = PortMapping()
    pm.add_digital("comp_out", direction=PortDirection.IN)
    pm.add_analog("v_cmp", direction=PortDirection.OUT)
    pm.a2d("v_cmp", "comp_out", threshold=0.9, invert=False)
    spec = pm.get_a2d("v_cmp")
    assert spec == ("comp_out", 0.9, False, "")


@toffee_test.testcase
async def test_a2d_requires_declared_ports():
    """Test that a2d raises KeyError for undeclared ports."""
    pm = PortMapping()
    with pytest.raises(KeyError):
        pm.a2d("missing_analog", "comp_out")
    pm.add_analog("v_cmp", direction=PortDirection.OUT)
    with pytest.raises(KeyError):
        pm.a2d("v_cmp", "missing_digital")


@toffee_test.testcase
async def test_a2d_with_yadc_device():
    """Test that yadc_device field is correctly stored and retrieved."""
    pm = PortMapping()
    pm.add_digital("comp_out", direction=PortDirection.IN)
    pm.add_analog("v_cmp", direction=PortDirection.OUT)
    pm.a2d("v_cmp", "comp_out", threshold=1.2, invert=True, yadc_device="YADC1")
    spec = pm.get_a2d("v_cmp")
    assert spec == ("comp_out", 1.2, True, "YADC1")


@toffee_test.testcase
async def test_iter_d2a():
    pm = PortMapping()
    pm.add_digital("a", PortDirection.OUT).add_analog("x").d2a("a", "x", scale=2.0)
    items = list(pm.iter_d2a())
    assert items == [("a", "x", 2.0, 0.0)]


@toffee_test.testcase
async def test_iter_d2a_param():
    pm = PortMapping()
    pm.add_digital("r_ctrl", PortDirection.OUT)
    pm.add_analog("r_load", PortDirection.IN)
    pm.d2a_param("r_ctrl", "r_load", mapping={0: 1e3})
    items = list(pm.iter_d2a_param())
    assert items == [("r_ctrl", "r_load", {0: 1e3})]


@toffee_test.testcase
async def test_iter_a2d():
    pm = PortMapping()
    pm.add_digital("comp_out", direction=PortDirection.IN)
    pm.add_analog("v_cmp", direction=PortDirection.OUT)
    pm.a2d("v_cmp", "comp_out", threshold=0.9, invert=True, yadc_device="Y1")
    items = list(pm.iter_a2d())
    assert items == [("v_cmp", "comp_out", 0.9, True, "Y1")]


@toffee_test.testcase
async def test_a2d_defaults():
    """Test that a2d has correct defaults for threshold, invert, and yadc_device."""
    pm = PortMapping()
    pm.add_digital("comp_out", direction=PortDirection.IN)
    pm.add_analog("v_cmp", direction=PortDirection.OUT)
    pm.a2d("v_cmp", "comp_out")
    spec = pm.get_a2d("v_cmp")
    assert spec == ("comp_out", 0.9, False, "")
