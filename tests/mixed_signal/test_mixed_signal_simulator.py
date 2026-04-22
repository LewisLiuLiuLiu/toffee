import pytest
import asyncio

import toffee_test

from toffee.mixed_signal.mixed_signal_simulator import MixedSignalSimulator
from toffee.mixed_signal.port_mapping import PortMapping, PortDirection


class FakeDut:
    def __init__(self):
        self.dac_ctrl = 0
        self.comp_out = 0


class FakeXyce:
    def __init__(self):
        self.time = 0.0
        self.dac_calls = []
        self.param_calls = []
        self._read_values = {}

    def simulateUntil(self, t):
        self.time = t
        return (1, t)

    def updateTimeVoltagePairs(self, name, times, voltages):
        self.dac_calls.append((name, times, voltages))

    def setCircuitParameter(self, name, value):
        self.param_calls.append((name, value))
        return 1

    def read(self, name):
        return self._read_values.get(name, 0.0)

    def close(self):
        pass


@toffee_test.testcase
async def test_advance_applies_dac_bridge():
    dut = FakeDut()
    dut.dac_ctrl = 1
    xyce = FakeXyce()
    mapping = PortMapping()
    mapping.add_digital("dac_ctrl", PortDirection.OUT)
    mapping.add_analog("v_dac", PortDirection.IN)
    mapping.d2a("dac_ctrl", "v_dac", scale=1.8)

    sim = MixedSignalSimulator(xyce, dut, mapping)
    sim.advance_to(5e-9)

    assert xyce.time == 5e-9
    assert len(xyce.dac_calls) == 1
    name, times, voltages = xyce.dac_calls[0]
    assert name == "v_dac"
    assert voltages == [1.8, 1.8]


@toffee_test.testcase
async def test_step_time_advances_and_ticks():
    dut = FakeDut()
    xyce = FakeXyce()
    mapping = PortMapping()
    sim = MixedSignalSimulator(xyce, dut, mapping)
    sim.step_time(2e-9)
    assert xyce.time == 2e-9
    assert sim._current_time == 2e-9


@toffee_test.testcase
async def test_non_out_port_skipped():
    class FakeDutIn:
        dac_ctrl = 1

    dut = FakeDutIn()
    xyce = FakeXyce()
    mapping = PortMapping()
    mapping.add_digital("dac_ctrl", PortDirection.IN)
    mapping.add_analog("v_dac", PortDirection.IN)
    mapping.d2a("dac_ctrl", "v_dac", scale=1.8)

    sim = MixedSignalSimulator(xyce, dut, mapping)
    sim.advance_to(3e-9)
    assert xyce.dac_calls == []  # IN port should not drive analog


@toffee_test.testcase
async def test_backward_time_noop():
    dut = FakeDut()
    xyce = FakeXyce()
    mapping = PortMapping()
    sim = MixedSignalSimulator(xyce, dut, mapping)
    sim.advance_to(5e-9)
    sim.advance_to(2e-9)  # should be a silent no-op
    assert sim._current_time == 5e-9
    assert xyce.time == 5e-9


@toffee_test.testcase
async def test_advance_applies_param_bridge():
    class FakeDut2:
        r_load_ctrl = 2  # encoded as integer codes

    dut = FakeDut2()
    xyce = FakeXyce()
    mapping = PortMapping()
    mapping.add_digital("r_load_ctrl", PortDirection.OUT)
    mapping.add_analog("r_load", PortDirection.IN)
    mapping.d2a_param("r_load_ctrl", "r_load", mapping={0: 1e3, 1: 10e3, 2: 100e3})

    sim = MixedSignalSimulator(xyce, dut, mapping)
    sim.advance_to(3e-9)

    assert xyce.time == 3e-9
    assert xyce.param_calls == [("r_load", 100e3)]


@toffee_test.testcase
async def test_advance_applies_a2d_bridge():
    """Voltage > threshold should set digital pin to 1."""
    dut = FakeDut()
    xyce = FakeXyce()
    xyce._read_values["v_cmp"] = 1.5

    mapping = PortMapping()
    mapping.add_digital("comp_out", PortDirection.IN)
    mapping.add_analog("v_cmp", PortDirection.OUT)
    mapping.a2d("v_cmp", "comp_out", threshold=0.9)

    sim = MixedSignalSimulator(xyce, dut, mapping)
    sim.advance_to(1e-9)

    assert dut.comp_out == 1


@toffee_test.testcase
async def test_a2d_low_voltage_drives_zero():
    """Voltage < threshold should set digital pin to 0."""
    dut = FakeDut()
    dut.comp_out = 1  # start at 1, should be driven to 0
    xyce = FakeXyce()
    xyce._read_values["v_cmp"] = 0.3

    mapping = PortMapping()
    mapping.add_digital("comp_out", PortDirection.IN)
    mapping.add_analog("v_cmp", PortDirection.OUT)
    mapping.a2d("v_cmp", "comp_out", threshold=0.9)

    sim = MixedSignalSimulator(xyce, dut, mapping)
    sim.advance_to(1e-9)

    assert dut.comp_out == 0


class FakeXyceInner:
    """Fake underlying Xyce interface with YADC support."""

    def __init__(self, adc_names, state_rows, num_points):
        self._adc_names = adc_names
        self._state_rows = state_rows
        self._num_points = num_points

    def getTimeStatePairsADC(self):
        """Return (status, ADCnames, numADCnames, numPoints, timeArray, stateArray)."""
        time_array = [float(i) for i in range(self._num_points)]
        return (1, self._adc_names, len(self._adc_names),
                self._num_points, time_array, self._state_rows)


class FakeXyceWithYADC(FakeXyce):
    """FakeXyce that also has a _xyce inner object with YADC support."""

    def __init__(self, adc_names, state_rows, num_points):
        super().__init__()
        self._xyce = FakeXyceInner(adc_names, state_rows, num_points)


@toffee_test.testcase
async def test_a2d_yadc_uses_quantized_state_directly():
    """YADC quantized digital state should be used directly, not threshold-compared.

    Scenario: YADC returns digital state=1 for device 'YADC1'.
    The analog read() would return a low voltage (0.3) which is below threshold (0.9).
    If the code incorrectly applies threshold comparison to the YADC result,
    it would produce 0 instead of 1. The fix must use YADC's quantized value directly.
    """
    dut = FakeDut()

    # YADC returns state=1 for device 'YADC1'
    state_rows = [[1]]  # one ADC, one point, state=1
    xyce = FakeXyceWithYADC(
        adc_names=["YADC1"],
        state_rows=state_rows,
        num_points=1,
    )
    # Even though read() would return a low voltage, YADC should take precedence
    xyce._read_values["v_cmp"] = 0.3

    mapping = PortMapping()
    mapping.add_digital("comp_out", PortDirection.IN)
    mapping.add_analog("v_cmp", PortDirection.OUT)
    mapping.a2d("v_cmp", "comp_out", threshold=0.9, yadc_device="YADC1")

    sim = MixedSignalSimulator(xyce, dut, mapping)
    sim.advance_to(1e-9)

    # YADC says state=1, so digital_val should be 1 (not 0 from threshold)
    assert dut.comp_out == 1


@toffee_test.testcase
async def test_a2d_yadc_zero_state_used_directly():
    """YADC returns state=0, should produce digital 0 even if voltage >= threshold."""
    dut = FakeDut()
    dut.comp_out = 1

    # YADC returns state=0 for device 'YADC1'
    state_rows = [[0]]  # one ADC, one point, state=0
    xyce = FakeXyceWithYADC(
        adc_names=["YADC1"],
        state_rows=state_rows,
        num_points=1,
    )
    # read() would return a high voltage, but YADC should take precedence
    xyce._read_values["v_cmp"] = 1.5

    mapping = PortMapping()
    mapping.add_digital("comp_out", PortDirection.IN)
    mapping.add_analog("v_cmp", PortDirection.OUT)
    mapping.a2d("v_cmp", "comp_out", threshold=0.9, yadc_device="YADC1")

    sim = MixedSignalSimulator(xyce, dut, mapping)
    sim.advance_to(1e-9)

    # YADC says state=0, so digital_val should be 0 (not 1 from threshold)
    assert dut.comp_out == 0


@toffee_test.testcase
async def test_a2d_yadc_invert_applied():
    """YADC quantized state with invert should flip the value."""
    dut = FakeDut()

    # YADC returns state=1 for device 'YADC1', with invert=True should become 0
    state_rows = [[1]]
    xyce = FakeXyceWithYADC(
        adc_names=["YADC1"],
        state_rows=state_rows,
        num_points=1,
    )
    xyce._read_values["v_cmp"] = 0.3

    mapping = PortMapping()
    mapping.add_digital("comp_out", PortDirection.IN)
    mapping.add_analog("v_cmp", PortDirection.OUT)
    mapping.a2d("v_cmp", "comp_out", threshold=0.9, invert=True, yadc_device="YADC1")

    sim = MixedSignalSimulator(xyce, dut, mapping)
    sim.advance_to(1e-9)

    # YADC says state=1, inverted -> 0
    assert dut.comp_out == 0


@toffee_test.testcase
async def test_a2d_yadc_fallback_when_no_xyce_attr():
    """Without _xyce attribute, should fall back to threshold comparison."""
    dut = FakeDut()
    xyce = FakeXyce()  # no _xyce attribute
    xyce._read_values["v_cmp"] = 0.3

    mapping = PortMapping()
    mapping.add_digital("comp_out", PortDirection.IN)
    mapping.add_analog("v_cmp", PortDirection.OUT)
    mapping.a2d("v_cmp", "comp_out", threshold=0.9, yadc_device="YADC1")

    sim = MixedSignalSimulator(xyce, dut, mapping)
    sim.advance_to(1e-9)

    # No _xyce, so fallback to threshold: 0.3 < 0.9 -> 0
    assert dut.comp_out == 0


@toffee_test.testcase
async def test_a2d_threshold_invert():
    """Verify invert works on the threshold (non-YADC) path."""
    dut = FakeDut()
    xyce = FakeXyce()
    xyce._read_values["v_cmp"] = 1.5  # above threshold
    mapping = PortMapping()
    mapping.add_digital("comp_out", PortDirection.IN)
    mapping.add_analog("v_cmp", PortDirection.OUT)
    mapping.a2d("v_cmp", "comp_out", threshold=0.9, invert=True)
    sim = MixedSignalSimulator(xyce, dut, mapping)
    sim.advance_to(1e-9)
    assert dut.comp_out == 0  # 1.5 >= 0.9 → 1, inverted → 0


@toffee_test.testcase
async def test_d2a_param_unmapped_code_raises():
    """Verify that an unmapped digital code in d2a_param raises ValueError."""
    dut = FakeDut()
    dut.dac_ctrl = 99  # not in mapping
    xyce = FakeXyce()
    mapping = PortMapping()
    mapping.add_digital("dac_ctrl", PortDirection.OUT)
    mapping.add_analog("v_dac", PortDirection.IN)
    mapping.d2a_param("dac_ctrl", "v_dac", mapping={0: 0.0, 1: 1.0})
    sim = MixedSignalSimulator(xyce, dut, mapping)
    with pytest.raises(ValueError, match="not in d2a_param mapping"):
        sim.advance_to(1e-9)


@toffee_test.testcase
async def test_d2a_param_in_port_skipped():
    """Verify that d2a_param with a non-OUT digital direction is skipped."""
    class FakeDutWithCtrl:
        r_ctrl = 2

    dut = FakeDutWithCtrl()
    xyce = FakeXyce()
    mapping = PortMapping()
    # r_ctrl is IN, not OUT, so d2a_param should be skipped
    mapping.add_digital("r_ctrl", PortDirection.IN)
    mapping.add_analog("r_load", PortDirection.IN)
    mapping.d2a_param("r_ctrl", "r_load", mapping={0: 1e3, 1: 10e3, 2: 100e3})

    sim = MixedSignalSimulator(xyce, dut, mapping)
    sim.advance_to(3e-9)

    # IN port should not drive analog parameters
    assert xyce.param_calls == []
