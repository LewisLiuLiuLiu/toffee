"""Tests for DutPin and MixedSignalBundle."""
import asyncio
import pytest


class MockPin:
    def __init__(self, value=0):
        self.value = value


class MockDut:
    def __init__(self):
        self.vin_ctrl = MockPin(0)
        self.charge_done = MockPin(0)


class TestDutPin:
    def test_write_sets_dut_pin(self):
        from toffee.mixed_signal.mixed_signal_bundle import DutPin
        dut = MockDut()
        pin = DutPin("vin_ctrl", dut)
        pin.value = 1
        assert dut.vin_ctrl.value == 1

    def test_read_returns_dut_pin(self):
        from toffee.mixed_signal.mixed_signal_bundle import DutPin
        dut = MockDut()
        dut.charge_done.value = 1
        pin = DutPin("charge_done", dut)
        assert pin.value == 1

class TestMixedSignalBundle:
    def test_bind_dut_pin_creates_dut_pin(self):
        from toffee.mixed_signal.mixed_signal_bundle import (
            DutPin, MixedSignalBundle,
        )
        dut = MockDut()
        bundle = MixedSignalBundle(dut=dut)
        pin = bundle.bind_dut_pin("vin", "vin_ctrl")
        assert isinstance(pin, DutPin)
        assert bundle.vin is pin
        bundle.vin.value = 1
        assert dut.vin_ctrl.value == 1

    def test_mixed_bundle_has_both_stimulus_and_pins(self):
        from toffee.mixed_signal.mixed_signal_bundle import (
            MixedSignalBundle,
        )
        sim = type("Sim", (), {
            "clock_event": asyncio.Event(),
            "events": {"step": asyncio.Event()},
            "set_source": lambda self, n, v: None,
            "read": lambda self, n: 0.0,
        })()
        dut = MockDut()
        bundle = MixedSignalBundle(sim, dut)
        bundle.bind_stimulus("vref", "VREF")
        bundle.bind_dut_pin("clk", "vin_ctrl")
        bundle.vref.value = 1.8
        bundle.clk.value = 1
        assert dut.vin_ctrl.value == 1
