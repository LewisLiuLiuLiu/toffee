"""Phase 0 end-to-end test: ngspice backend with AnalogEnv/Agent.

Uses the fixed two-stage op-amp netlist.  The DC operating point is
chosen so that the second-stage NMOS load operates in saturation.
"""

import os
import tempfile

import toffee_test
from toffee import driver_method
from toffee.analog.analog_bundle import AnalogBundle
from toffee.analog.analog_agent import AnalogAgent
from toffee.analog.analog_env import AnalogEnv
from toffee.analog.ngspice_simulator import NgSpiceSimulator


class OpampAgent(AnalogAgent):
    @driver_method()
    async def measure_vout(self):
        return self.simulator.read("v(vout)")


class OpampEnv(AnalogEnv):
    def __init__(self):
        tb = os.path.join(tempfile.gettempdir(), "toffee_opamp_ngspice.cir")
        netlist = (
            "/mnt/d/ongoingProjects/openEDA/toffee_project/"
            "toffee_ana/SPICE-Netlists/opamp_2stage_180nm_design_netlist.sp"
        )
        with open(tb, "w") as f:
            f.write("* Opamp testbench\n")
            f.write("VDD VDD 0 DC 1.8\n")
            f.write("VSS VSS 0 DC 0\n")
            f.write("VINP VINP 0 DC 1.2\n")
            f.write("VINN VINN 0 DC 1.2\n")
            f.write("IBIAS VDD VBIAS DC 100u\n")
            f.write(f".include {netlist}\n")
            f.write(".end\n")

        simulator = NgSpiceSimulator(tb)
        super().__init__(simulator)

        self.bundle = AnalogBundle(simulator)
        self.bundle.bind_signal("v(vout)")

        self.agent = OpampAgent(simulator=simulator)


@toffee_test.fixture
async def opamp_env(toffee_request):
    env = toffee_request.create_env(OpampEnv)
    yield env


@toffee_test.testcase
async def test_opamp_dc_ngspice(opamp_env):
    opamp_env.simulator.run_analysis([".op"], save_vars=["@m5[vdsat]"])
    vout = await opamp_env.agent.measure_vout()
    vdsat_m5 = opamp_env.simulator.read("v(@m5[vdsat])")
    print(f"\n[ngspice opamp DC] vout = {vout} V, M5 Vdsat = {vdsat_m5} V\n")
    assert isinstance(vout, float)
    # Saturation condition for the second-stage NMOS load: Vds > Vdsat
    assert vout > vdsat_m5, f"Expected Vds ({vout} V) > Vdsat ({vdsat_m5} V) for saturation"
    assert opamp_env.simulator.read("v(vdd)") == 1.8
