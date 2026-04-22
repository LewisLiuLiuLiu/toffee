# tests/mixed_signal/test_sar_adc_xyce.py
import os
import tempfile

import toffee_test
from toffee import driver_method
from toffee.analog.xyce_simulator import XyceSimulator
from toffee.mixed_signal.mixed_signal_simulator import MixedSignalSimulator
from toffee.mixed_signal.port_mapping import PortMapping, PortDirection
from toffee.mixed_signal.step_strategy import StepExactStrategy


class FakeSarDut:
    """Fake digital SAR that outputs a 2-bit thermometer code to a DAC."""

    def __init__(self):
        self.dac_code = 0

    def set_code(self, code: int):
        self.dac_code = code


class SarEnv:
    def __init__(self):
        tb = os.path.join(tempfile.gettempdir(), "toffee_sar_adc.cir")
        with open(tb, "w") as f:
            f.write("* SAR ADC testbench\n")
            f.write(".global_param v_dac=0\n")
            f.write("V1 dac_in 0 DC {v_dac}\n")
            f.write("R1 dac_in vout 1k\n")
            f.write("C1 vout 0 1p\n")
            f.write(".tran 0.01n 10n\n")
            f.write(".print tran V(vout)\n")
            f.write(".end\n")

        xyce = XyceSimulator(tb)
        self.dut = FakeSarDut()
        mapping = PortMapping()
        mapping.add_digital("dac_code", PortDirection.OUT)
        mapping.add_analog("dac_in", PortDirection.IN)
        # code 0 -> 0V, 1 -> 0.6V, 2 -> 1.2V, 3 -> 1.8V
        mapping.d2a_param(
            "dac_code", "v_dac", mapping={0: 0.0, 1: 0.6, 2: 1.2, 3: 1.8}
        )

        self.sim = MixedSignalSimulator(
            xyce, self.dut, mapping, step_strategy=StepExactStrategy(max_step=0.5e-9)
        )


@toffee_test.fixture
async def sar_env(toffee_request):
    env = toffee_request.create_env(SarEnv)
    yield env


@toffee_test.testcase
async def test_sar_adc_step_response(sar_env):
    sar_env.dut.set_code(3)
    sar_env.sim.advance_to(2e-9)
    vout = sar_env.sim.read("V(VOUT)")
    # At 2ns the RC should be close to 1.8V
    assert vout > 1.5, f"Expected vout > 1.5V at 2ns, got {vout}"
