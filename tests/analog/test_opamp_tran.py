"""TRAN step response test for two-stage op-amp."""
import os
import tempfile

import toffee_test
from toffee import driver_method, monitor_method
from toffee.analog.analog_bundle import AnalogBundle
from toffee.analog.analog_agent import AnalogAgent
from toffee.analog.analog_env import AnalogEnv
from toffee.analog.ngspice_simulator import NgSpiceSimulator
from toffee.asynchronous import start_clock


class OpampTranAgent(AnalogAgent):
    def __init__(self, simulator):
        super().__init__(simulator=simulator, event_name="step")

    @driver_method()
    async def set_input(self, vinp, vinn):
        self.simulator.set_vsrc("VINP", vinp)
        self.simulator.set_vsrc("VINN", vinn)

    @driver_method()
    async def read_vout(self):
        return self.simulator.read("v(vout)")

    @monitor_method()
    async def sample_vout(self):
        return self.simulator.read("v(vout)")


class OpampTranEnv(AnalogEnv):
    def __init__(self):
        tb = os.path.join(tempfile.gettempdir(), "toffee_opamp_tran.cir")
        netlist = (
            "/mnt/d/ongoingProjects/openEDA/toffee_project/"
            "toffee_ana/SPICE-Netlists/opamp_2stage_180nm_design_netlist.sp"
        )
        with open(tb, "w") as f:
            f.write("* Opamp TRAN testbench\n")
            f.write("VDD VDD 0 DC 1.8\n")
            f.write("VSS VSS 0 DC 0\n")
            f.write("VINP VINP 0 DC 0 external\n")
            f.write("VINN VINN 0 DC 0 external\n")
            f.write("IBIAS VDD VBIAS DC 100u\n")
            f.write(f".include {netlist}\n")
            f.write(".end\n")

        simulator = NgSpiceSimulator(tb)
        super().__init__(simulator)
        self.bundle = AnalogBundle(simulator)
        self.bundle.bind_signal("v(vout)")
        self.agent = OpampTranAgent(simulator=simulator)


@toffee_test.fixture
async def opamp_tran_env(toffee_request):
    env = toffee_request.create_env(OpampTranEnv)
    yield env


@toffee_test.testcase
async def test_opamp_step_response(opamp_tran_env):
    agent = opamp_tran_env.agent

    # Set initial condition before starting the event loop
    await agent.set_input(vinp=1.2, vinn=1.2)

    # Start the event loop
    start_clock(opamp_tran_env.simulator)

    # Start Monitor sampling
    agent.start_monitor("sample_vout", maxsize=200)

    # Let the initial DC operating point settle
    for _ in range(20):
        await agent.monitor_step()

    # Apply step: vinp from 1.2V to 1.3V
    await agent.set_input(vinp=1.3, vinn=1.2)

    # Wait for step response to settle
    for _ in range(80):
        await agent.monitor_step()

    # Collect sampled data
    samples = []
    while agent.monitor_size("sample_vout") > 0:
        samples.append(await agent.sample_vout())

    print(f"\n[opamp TRAN] {len(samples)} samples collected")
    if len(samples) >= 2:
        print(f"  vout start: {samples[0]:.3f}V, end: {samples[-1]:.3f}V\n")

    # Verify vout changed after step
    assert len(samples) > 1, f"Only {len(samples)} samples, expected more"
    assert abs(samples[-1] - samples[0]) > 0.05, (
        f"Expected vout response to step, got {samples[0]:.3f} -> {samples[-1]:.3f}"
    )
