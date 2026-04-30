"""Verify NgSpiceSimulator exposes the MixedSignalSimulator-compatible API."""
import os
import tempfile

import pytest
import toffee_test

try:
    from toffee.analog.ngspice_simulator import NgSpiceSimulator

    _HAS_NGSPICE = True
except (ImportError, OSError):
    _HAS_NGSPICE = False

pytestmark = pytest.mark.skipif(not _HAS_NGSPICE, reason="libngspice not available")


def _make_rc_netlist() -> str:
    """Write a minimal RC circuit netlist and return its path."""
    path = os.path.join(tempfile.mkdtemp(prefix="toffee_ng_compat_"), "rc.cir")
    with open(path, "w") as f:
        f.write("* RC for NgSpice MixedSignal compat test\n")
        f.write("V1 in 0 DC 0 external\n")
        f.write("R1 in out 1k\n")
        f.write("C1 out 0 1p\n")
        f.write(".end\n")
    return path


@toffee_test.testcase
async def test_simulate_until_returns_tuple():
    sim = NgSpiceSimulator(_make_rc_netlist())
    try:
        result = sim.simulateUntil(1e-9)
        assert isinstance(result, tuple)
        assert len(result) == 2
        status, actual = result
        assert status == 1
        assert actual >= 1e-9
    finally:
        sim.finish()


@toffee_test.testcase
async def test_update_time_voltage_pairs():
    sim = NgSpiceSimulator(_make_rc_netlist())
    try:
        sim.updateTimeVoltagePairs("V1", [0.0, 1e-9], [1.8, 1.8])
        sim.simulateUntil(1e-9)
        vout = sim.read("V(out)")
        assert vout > 0.5, f"Expected V(out) > 0.5V after driving 1.8V, got {vout}"
    finally:
        sim.finish()


@toffee_test.testcase
async def test_set_circuit_parameter():
    path = os.path.join(tempfile.mkdtemp(prefix="toffee_ng_param_"), "param.cir")
    with open(path, "w") as f:
        f.write("* param test\n")
        f.write(".param v_dac=0\n")
        f.write("V1 in 0 DC {v_dac}\n")
        f.write("R1 in out 1k\n")
        f.write("C1 out 0 1p\n")
        f.write(".end\n")
    sim = NgSpiceSimulator(path)
    try:
        # Should not raise; return value is best-effort
        result = sim.setCircuitParameter("v_dac", 1.8)
        assert result in (0, 1)
    finally:
        sim.finish()


@toffee_test.testcase
async def test_mixed_signal_simulator_with_ngspice():
    """Full integration: MixedSignalSimulator + NgSpiceSimulator + PortMapping."""
    from toffee.mixed_signal.mixed_signal_simulator import MixedSignalSimulator
    from toffee.mixed_signal.port_mapping import PortMapping, PortDirection
    from toffee.mixed_signal.step_strategy import StepExactStrategy

    class FakeDut:
        vin_ctrl = 1

    path = os.path.join(tempfile.mkdtemp(prefix="toffee_ng_ms_"), "ms.cir")
    with open(path, "w") as f:
        f.write("* Mixed-signal compat\n")
        f.write("V1 vin 0 DC 0 external\n")
        f.write("R1 vin vout 1k\n")
        f.write("C1 vout 0 1p\n")
        f.write(".end\n")

    sim = NgSpiceSimulator(path)
    try:
        dut = FakeDut()
        mapping = PortMapping()
        mapping.add_digital("vin_ctrl", PortDirection.OUT)
        mapping.add_analog("V1", PortDirection.IN)
        mapping.d2a("vin_ctrl", "V1", scale=1.8)
        ms = MixedSignalSimulator(
            sim, dut, mapping,
            step_strategy=StepExactStrategy(max_step=1e-9),
        )
        ms.advance_to(5e-9)
        vout = ms.read("V(vout)")
        assert vout > 1.0, f"Expected vout > 1.0V, got {vout}"
    finally:
        sim.finish()
