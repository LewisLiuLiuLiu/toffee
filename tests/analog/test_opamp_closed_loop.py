"""Closed-loop unity-gain buffer test."""
import os
import tempfile

import toffee_test
from toffee import driver_method, monitor_method
from toffee.analog.analog_bundle import AnalogBundle
from toffee.analog.analog_agent import AnalogAgent
from toffee.analog.analog_env import AnalogEnv
from toffee.analog.ngspice_simulator import NgSpiceSimulator
from toffee._compare import tolerance_compare
from toffee.asynchronous import start_clock


class BufferAgent(AnalogAgent):
    def __init__(self, simulator):
        super().__init__(
            simulator=simulator,
            event_name="step",
            compare_func=tolerance_compare(0.05),
        )

    @driver_method()
    async def set_input(self, vin):
        self.simulator.set_vsrc("VIN", vin)

    @driver_method()
    async def read_vout(self):
        return self.simulator.read("v(vout)")

    @monitor_method()
    async def sample_vout(self):
        return self.simulator.read("v(vout)")


class BufferEnv(AnalogEnv):
    def __init__(self):
        tb = os.path.join(tempfile.gettempdir(), "toffee_buffer.cir")
        netlist = (
            "/mnt/d/ongoingProjects/openEDA/toffee_project/"
            "toffee_ana/SPICE-Netlists/opamp_2stage_180nm_design_netlist.sp"
        )
        with open(tb, "w") as f:
            f.write("* Unity-gain buffer testbench\n")
            f.write("VDD VDD 0 DC 1.8\n")
            f.write("VSS VSS 0 DC 0\n")
            f.write("VIN VINP 0 DC 0 external\n")
            f.write("RFB VINN VOUT 1u\n")
            f.write("IBIAS VDD VBIAS DC 100u\n")
            f.write(".nodeset V(VOUT)=1.0 V(N2)=0.5\n")
            f.write(f".include {netlist}\n")
            f.write(".end\n")

        simulator = NgSpiceSimulator(tb)
        super().__init__(simulator)
        self.bundle = AnalogBundle(simulator)
        self.bundle.bind_signal("v(vout)")
        self.agent = BufferAgent(simulator=simulator)


@toffee_test.fixture
async def buffer_env(toffee_request):
    env = toffee_request.create_env(BufferEnv)
    yield env


@toffee_test.testcase
async def test_buffer_following(buffer_env):
    agent = buffer_env.agent
    sim = buffer_env.simulator

    # Set input to 1.0V (matching the nodeset)
    await agent.set_input(vin=1.0)
    start_clock(sim)
    agent.start_monitor("sample_vout", maxsize=500)

    # Let it settle for longer
    for _ in range(200):
        await agent.monitor_step()

    # Read vout, vinp, vinn to verify buffer operation
    vout = await agent.read_vout()
    vinp = sim.read("v(vinp)")
    vinn = sim.read("v(vinn)")
    error = abs(vout - 1.0)

    print(f"Buffer test: vinp={vinp:.3f}V vinn={vinn:.3f}V vout={vout:.3f}V error={error*1000:.1f}mV")

    # Verify unity-gain buffer: vout ≈ vinp ≈ 1.0V, vinn ≈ vout (feedback)
    assert abs(vinp - 1.0) < 0.05, f"VINP={vinp:.3f}V not 1.0V"
    assert abs(vinn - vout) < 0.05, f"VINN={vinn:.3f}V != VOUT={vout:.3f}V (feedback broken)"
    assert abs(vout - 1.0) < 0.2, f"Buffer error {error*1000:.1f}mV exceeds 200mV"
