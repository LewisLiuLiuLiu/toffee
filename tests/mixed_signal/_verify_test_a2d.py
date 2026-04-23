"""Verification tests for PortMapping A2D + MixedSignalSimulator A2D logic.

These tests are written by the independent verifier to confirm:
1. No old API names (bridge, BridgeSpec, etc.) remain in public API
2. A2DSpec has correct fields
3. YADC values are used DIRECTLY (no double threshold)
4. Safe invert logic handles non-binary YADC values
5. Threshold boundary (voltage == threshold) is handled correctly
6. Multiple YADC devices are mapped correctly
"""

import pytest
import toffee_test

from toffee.mixed_signal.port_mapping import (
    PortMapping, PortDirection, D2ASpec, D2AParamSpec, A2DSpec,
)
from toffee.mixed_signal.mixed_signal_simulator import MixedSignalSimulator


# --- Helpers ---

class SimpleDut:
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


class FakeAnalog:
    """Minimal analog simulator fake."""
    def __init__(self):
        self.time = 0.0
        self._reads = {}

    def simulateUntil(self, t):
        self.time = t
        return (1, t)

    def read(self, name):
        return self._reads.get(name, 0.0)

    def updateTimeVoltagePairs(self, name, times, voltages):
        pass


class FakeXyceInner:
    """Inner Xyce with getTimeStatePairsADC."""
    def __init__(self, adc_names, state_rows, num_points):
        self._adc_names = adc_names
        self._state_rows = state_rows
        self._num_points = num_points

    def getTimeStatePairsADC(self):
        time_array = [float(i) for i in range(self._num_points)]
        return (1, self._adc_names, len(self._adc_names),
                self._num_points, time_array, self._state_rows)


class FakeAnalogWithYADC(FakeAnalog):
    def __init__(self, adc_names, state_rows, num_points):
        super().__init__()
        self._xyce = FakeXyceInner(adc_names, state_rows, num_points)


# ===== 1. A2DSpec fields =====

@toffee_test.testcase
async def test_a2dspec_fields():
    """A2DSpec must have exactly: digital_name, threshold, invert, yadc_device."""
    spec = A2DSpec(digital_name="out", threshold=1.5, invert=True, yadc_device="Y1")
    assert spec.digital_name == "out"
    assert spec.threshold == 1.5
    assert spec.invert is True
    assert spec.yadc_device == "Y1"


@toffee_test.testcase
async def test_a2dspec_defaults():
    """Default threshold=0.9, invert=False, yadc_device=''."""
    spec = A2DSpec(digital_name="x")
    assert spec.threshold == 0.9
    assert spec.invert is False
    assert spec.yadc_device == ""


# ===== 2. No old API names =====

@toffee_test.testcase
async def test_no_old_api_names():
    """PortMapping should NOT have bridge/BridgeSpec/reverse_bridge methods."""
    pm = PortMapping()
    assert not hasattr(pm, "bridge")
    assert not hasattr(pm, "reverse_bridge")
    assert not hasattr(pm, "iter_voltage_bridges")
    assert not hasattr(pm, "iter_param_bridges")


@toffee_test.testcase
async def test_no_old_spec_classes():
    """Old class names should not exist in the module."""
    import toffee.mixed_signal.port_mapping as mod
    assert not hasattr(mod, "BridgeSpec")
    assert not hasattr(mod, "ParamBridgeSpec")


# ===== 3. Threshold boundary =====

@toffee_test.testcase
async def test_threshold_exact_boundary():
    """voltage == threshold should produce digital 1 (>= comparison)."""
    dut = SimpleDut(comp_out=0)
    analog = FakeAnalog()
    analog._reads["v_cmp"] = 0.9  # exactly at threshold

    mapping = PortMapping()
    mapping.add_digital("comp_out", PortDirection.IN)
    mapping.add_analog("v_cmp", PortDirection.OUT)
    mapping.a2d("v_cmp", "comp_out", threshold=0.9)

    sim = MixedSignalSimulator(analog, dut, mapping)
    sim.advance_to(1e-9)
    assert dut.comp_out == 1  # >= threshold


# ===== 4. YADC direct value (no re-thresholding) =====

@toffee_test.testcase
async def test_yadc_value_not_thresholded():
    """YADC returns integer state; it should NOT be compared against threshold.

    Setup: YADC returns state=1, but if treated as a voltage and compared
    against threshold=0.9, it would STILL pass. So we use threshold=2.0
    to distinguish: if code incorrectly does `1 >= 2.0`, result is 0 (WRONG).
    Correct code uses 1 directly.
    """
    dut = SimpleDut(comp_out=0)

    analog = FakeAnalogWithYADC(
        adc_names=["YADC1"],
        state_rows=[[1]],  # state=1
        num_points=1,
    )
    analog._reads["v_cmp"] = 0.3

    mapping = PortMapping()
    mapping.add_digital("comp_out", PortDirection.IN)
    mapping.add_analog("v_cmp", PortDirection.OUT)
    # threshold=2.0: if code mistakenly does `1 >= 2.0`, gives 0
    mapping.a2d("v_cmp", "comp_out", threshold=2.0, yadc_device="YADC1")

    sim = MixedSignalSimulator(analog, dut, mapping)
    sim.advance_to(1e-9)
    assert dut.comp_out == 1  # YADC state=1, used directly


# ===== 5. Safe invert with non-binary YADC values =====

@toffee_test.testcase
async def test_invert_safe_with_nonbinary_yadc():
    """If YADC returns state=2 (truthy), invert should give 0, not -1.

    Old unsafe: 1 - 2 = -1 (WRONG)
    Safe: 0 if 2 else 1 → 0 (CORRECT)
    """
    dut = SimpleDut(comp_out=99)

    analog = FakeAnalogWithYADC(
        adc_names=["Y1"],
        state_rows=[[2]],  # non-binary truthy value
        num_points=1,
    )
    analog._reads["v_cmp"] = 0.0

    mapping = PortMapping()
    mapping.add_digital("comp_out", PortDirection.IN)
    mapping.add_analog("v_cmp", PortDirection.OUT)
    mapping.a2d("v_cmp", "comp_out", invert=True, yadc_device="Y1")

    sim = MixedSignalSimulator(analog, dut, mapping)
    sim.advance_to(1e-9)
    assert dut.comp_out == 0  # 2 is truthy → inverted = 0 (not -1)


@toffee_test.testcase
async def test_invert_zero_becomes_one():
    """Invert: state=0 (falsy) should become 1."""
    dut = SimpleDut(comp_out=99)

    analog = FakeAnalogWithYADC(
        adc_names=["Y1"],
        state_rows=[[0]],
        num_points=1,
    )
    analog._reads["v_cmp"] = 0.0

    mapping = PortMapping()
    mapping.add_digital("comp_out", PortDirection.IN)
    mapping.add_analog("v_cmp", PortDirection.OUT)
    mapping.a2d("v_cmp", "comp_out", invert=True, yadc_device="Y1")

    sim = MixedSignalSimulator(analog, dut, mapping)
    sim.advance_to(1e-9)
    assert dut.comp_out == 1  # 0 is falsy → inverted = 1


# ===== 6. Multiple YADC devices =====

@toffee_test.testcase
async def test_multiple_yadc_devices():
    """Multiple A2D channels with different YADC devices should each get correct value."""
    dut = SimpleDut(pin_a=0, pin_b=0)

    analog = FakeAnalogWithYADC(
        adc_names=["YADC_A", "YADC_B"],
        state_rows=[[1], [0]],  # A=1, B=0
        num_points=1,
    )
    analog._reads["v_a"] = 0.0
    analog._reads["v_b"] = 5.0

    mapping = PortMapping()
    mapping.add_digital("pin_a", PortDirection.IN)
    mapping.add_digital("pin_b", PortDirection.IN)
    mapping.add_analog("v_a", PortDirection.OUT)
    mapping.add_analog("v_b", PortDirection.OUT)
    mapping.a2d("v_a", "pin_a", yadc_device="YADC_A")
    mapping.a2d("v_b", "pin_b", yadc_device="YADC_B")

    sim = MixedSignalSimulator(analog, dut, mapping)
    sim.advance_to(1e-9)

    assert dut.pin_a == 1  # YADC_A state=1
    assert dut.pin_b == 0  # YADC_B state=0


# ===== 7. YADC failure fallback =====

@toffee_test.testcase
async def test_yadc_failure_falls_back_to_threshold():
    """If getTimeStatePairsADC raises RuntimeError, fallback to threshold."""
    class FailingXyceInner:
        def getTimeStatePairsADC(self):
            raise RuntimeError("YADC not available")

    dut = SimpleDut(comp_out=0)
    analog = FakeAnalog()
    analog._xyce = FailingXyceInner()
    analog._reads["v_cmp"] = 1.5  # above threshold

    mapping = PortMapping()
    mapping.add_digital("comp_out", PortDirection.IN)
    mapping.add_analog("v_cmp", PortDirection.OUT)
    mapping.a2d("v_cmp", "comp_out", threshold=0.9, yadc_device="YADC1")

    sim = MixedSignalSimulator(analog, dut, mapping)
    sim.advance_to(1e-9)
    assert dut.comp_out == 1  # fallback: 1.5 >= 0.9


# ===== 8. step_time validation =====

@toffee_test.testcase
async def test_step_time_negative_raises():
    """step_time with negative dt should raise ValueError."""
    dut = SimpleDut()
    analog = FakeAnalog()
    mapping = PortMapping()
    sim = MixedSignalSimulator(analog, dut, mapping)
    with pytest.raises(ValueError, match="positive dt"):
        sim.step_time(-1e-9)


@toffee_test.testcase
async def test_step_time_zero_raises():
    """step_time with zero dt should raise ValueError."""
    dut = SimpleDut()
    analog = FakeAnalog()
    mapping = PortMapping()
    sim = MixedSignalSimulator(analog, dut, mapping)
    with pytest.raises(ValueError, match="positive dt"):
        sim.step_time(0)


# ===== 9. Pin with .value attribute =====

@toffee_test.testcase
async def test_a2d_writes_to_pin_value_attr():
    """If the DUT pin has a .value attribute, it should be used."""
    class Pin:
        def __init__(self):
            self.value = 0

    class DutWithPin:
        def __init__(self):
            self.comp_out = Pin()

    dut = DutWithPin()
    analog = FakeAnalog()
    analog._reads["v_cmp"] = 1.5

    mapping = PortMapping()
    mapping.add_digital("comp_out", PortDirection.IN)
    mapping.add_analog("v_cmp", PortDirection.OUT)
    mapping.a2d("v_cmp", "comp_out", threshold=0.9)

    sim = MixedSignalSimulator(analog, dut, mapping)
    sim.advance_to(1e-9)
    assert dut.comp_out.value == 1
