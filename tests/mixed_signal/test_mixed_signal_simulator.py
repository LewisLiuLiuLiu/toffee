import pytest
import asyncio

from toffee.mixed_signal.mixed_signal_simulator import MixedSignalSimulator
from toffee.mixed_signal.port_mapping import PortMapping, PortDirection


class FakeDut:
    def __init__(self):
        self.dac_ctrl = 0


class FakeXyce:
    def __init__(self):
        self.time = 0.0
        self.dac_calls = []
        self.param_calls = []

    def simulateUntil(self, t):
        self.time = t
        return (1, t)

    def updateTimeVoltagePairs(self, name, times, voltages):
        self.dac_calls.append((name, times, voltages))

    def setCircuitParameter(self, name, value):
        self.param_calls.append((name, value))
        return 1

    def close(self):
        pass


def test_advance_applies_dac_bridge():
    dut = FakeDut()
    dut.dac_ctrl = 1
    xyce = FakeXyce()
    mapping = PortMapping()
    mapping.add_digital("dac_ctrl", PortDirection.OUT)
    mapping.add_analog("v_dac", PortDirection.IN)
    mapping.bridge("dac_ctrl", "v_dac", scale=1.8)

    sim = MixedSignalSimulator(xyce, dut, mapping)
    sim.advance_to(5e-9)

    assert xyce.time == 5e-9
    assert len(xyce.dac_calls) == 1
    name, times, voltages = xyce.dac_calls[0]
    assert name == "v_dac"
    assert voltages == [1.8, 1.8]


def test_step_time_advances_and_ticks():
    dut = FakeDut()
    xyce = FakeXyce()
    mapping = PortMapping()
    sim = MixedSignalSimulator(xyce, dut, mapping)
    sim.step_time(2e-9)
    assert xyce.time == 2e-9
    assert sim._current_time == 2e-9


def test_non_out_port_skipped():
    class FakeDutIn:
        dac_ctrl = 1

    dut = FakeDutIn()
    xyce = FakeXyce()
    mapping = PortMapping()
    mapping.add_digital("dac_ctrl", PortDirection.IN)
    mapping.add_analog("v_dac", PortDirection.IN)
    mapping.bridge("dac_ctrl", "v_dac", scale=1.8)

    sim = MixedSignalSimulator(xyce, dut, mapping)
    sim.advance_to(3e-9)
    assert xyce.dac_calls == []  # IN port should not drive analog


def test_backward_time_raises():
    dut = FakeDut()
    xyce = FakeXyce()
    mapping = PortMapping()
    sim = MixedSignalSimulator(xyce, dut, mapping)
    sim.advance_to(5e-9)
    with pytest.raises(ValueError):
        sim.advance_to(2e-9)
