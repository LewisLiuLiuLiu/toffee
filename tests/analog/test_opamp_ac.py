"""AC analysis test for two-stage op-amp."""
import math
import os
import tempfile

import toffee_test
from toffee import driver_method
from toffee.analog.analog_bundle import AnalogBundle
from toffee.analog.analog_agent import AnalogAgent
from toffee.analog.analog_env import AnalogEnv
from toffee.analog.ngspice_simulator import NgSpiceSimulator


class OpampACAgent(AnalogAgent):
    @driver_method()
    async def measure_vout_ac(self):
        return self.simulator.read("v(vout)")

    @driver_method()
    async def measure_frequency(self):
        return self.simulator.read("frequency")


class OpampACEnv(AnalogEnv):
    def __init__(self):
        tb = os.path.join(tempfile.gettempdir(), "toffee_opamp_ac.cir")
        netlist = (
            "/mnt/d/ongoingProjects/openEDA/toffee_project/"
            "toffee_ana/SPICE-Netlists/opamp_2stage_180nm_design_netlist.sp"
        )
        with open(tb, "w") as f:
            f.write("* Opamp AC testbench\n")
            f.write("VDD VDD 0 DC 1.8\n")
            f.write("VSS VSS 0 DC 0\n")
            f.write("VINP VINP 0 DC 1.2 AC 1\n")
            f.write("VINN VINN 0 DC 1.2\n")
            f.write("IBIAS VDD VBIAS DC 100u\n")
            f.write(f".include {netlist}\n")
            f.write(".end\n")

        simulator = NgSpiceSimulator(tb)
        super().__init__(simulator)
        self.bundle = AnalogBundle(simulator)
        self.bundle.bind_signal("v(vout)")
        self.agent = OpampACAgent(simulator=simulator)


def _ac_gain_db(vout_result) -> float:
    """Compute gain in dB from AC v(vout) (complex or list of complex)."""
    if isinstance(vout_result, list):
        vout_result = vout_result[0]
    mag = abs(vout_result)
    if mag == 0:
        return -float("inf")
    return 20.0 * math.log10(mag)


def _ac_phase_deg(vout_result) -> float:
    """Compute phase in degrees from AC v(vout) (complex or list of complex)."""
    if isinstance(vout_result, list):
        vout_result = vout_result[0]
    return math.degrees(math.atan2(vout_result.imag, vout_result.real))


@toffee_test.fixture
async def opamp_ac_env(toffee_request):
    env = toffee_request.create_env(OpampACEnv)
    yield env


@toffee_test.testcase
async def test_opamp_ac_gain(opamp_ac_env):
    opamp_ac_env.simulator.run_analysis([".ac dec 10 1 1G"])
    vout = await opamp_ac_env.agent.measure_vout_ac()
    gain_db = _ac_gain_db(vout)
    print(f"\n[ngspice opamp AC] low-freq gain = {gain_db:.1f} dB\n")
    assert gain_db > 40, f"Gain {gain_db:.1f}dB < 40dB spec"


@toffee_test.testcase
async def test_opamp_ac_phase_margin(opamp_ac_env):
    opamp_ac_env.simulator.run_analysis([".ac dec 10 1 1G"])

    vout = await opamp_ac_env.agent.measure_vout_ac()
    gain_db = _ac_gain_db(vout)
    phase_lf = _ac_phase_deg(vout)

    print(f"\n[ngspice opamp AC] low-freq phase = {phase_lf:.1f} deg, gain = {gain_db:.1f} dB\n")

    assert gain_db > 40, f"Gain {gain_db:.1f}dB < 40dB spec"
    assert phase_lf > -180, f"Phase {phase_lf:.1f} deg out of range"
