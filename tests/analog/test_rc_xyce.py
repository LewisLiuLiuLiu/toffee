"""Phase 0 end-to-end test: Xyce backend with AnalogEnv/Agent."""

import os
import tempfile

import toffee_test
from toffee import driver_method
from toffee.analog.analog_bundle import AnalogBundle
from toffee.analog.analog_agent import AnalogAgent
from toffee.analog.analog_env import AnalogEnv
from toffee.analog.xyce_simulator import XyceSimulator


class RCAgent(AnalogAgent):
    @driver_method()
    async def measure_vout(self):
        return self.simulator.read("V(OUT)")


class RCEnv(AnalogEnv):
    def __init__(self):
        tb = os.path.join(tempfile.gettempdir(), "toffee_rc_xyce.cir")
        with open(tb, "w") as f:
            f.write("* RC testbench for Xyce\n")
            f.write("V1 in 0 DC 1 PWL(0 0 1n 1)\n")
            f.write("R1 in out 1k\n")
            f.write("C1 out 0 1p\n")
            f.write(".tran 0.1n 10n\n")
            f.write(".print tran V(OUT)\n")
            f.write(".end\n")

        simulator = XyceSimulator(tb)
        super().__init__(simulator)

        self.bundle = AnalogBundle(simulator)
        self.bundle.bind_signal("V(OUT)")

        self.agent = RCAgent(simulator=simulator)


@toffee_test.fixture
async def rc_env(toffee_request):
    env = toffee_request.create_env(RCEnv)
    yield env


@toffee_test.testcase
async def test_rc_step_response(rc_env):
    rc_env.simulator.step_time(1e-9)
    v1 = await rc_env.agent.measure_vout()
    assert v1 < 0.5, f"Expected vout < 0.5V at 1ns, got {v1}"

    rc_env.simulator.advance_to(5e-9)
    v5 = await rc_env.agent.measure_vout()
    assert v5 > 0.9, f"Expected vout > 0.9V at 5ns, got {v5}"
