"""Tests for AnalogStimulus and AnalogObservation."""
import asyncio
import pytest


class MockSimulator:
    def __init__(self):
        self.sources = {}
        self._read_values = {}
        self.clock_event = asyncio.Event()
        self.events = {"step": self.clock_event}

    def set_source(self, name, value):
        self.sources[name] = value

    def read(self, name):
        return self._read_values.get(name, 0.0)


class TestAnalogStimulus:
    def test_write_calls_set_source(self):
        from toffee.analog.analog_signal import AnalogStimulus
        sim = MockSimulator()
        stim = AnalogStimulus("VINN", sim)
        stim.value = 1.8
        assert sim.sources["VINN"] == 1.8

    def test_read_returns_last_value(self):
        from toffee.analog.analog_signal import AnalogStimulus
        sim = MockSimulator()
        stim = AnalogStimulus("VINN", sim)
        stim.value = 1.8
        assert stim.value == 1.8

    def test_different_nodes_independent(self):
        from toffee.analog.analog_signal import AnalogStimulus
        sim = MockSimulator()
        vinn = AnalogStimulus("VINN", sim)
        vinp = AnalogStimulus("VINP", sim)
        vinn.value = 1.0
        vinp.value = 2.0
        assert sim.sources["VINN"] == 1.0
        assert sim.sources["VINP"] == 2.0


class TestAnalogBundleBinding:
    def test_bind_stimulus_creates_analog_stimulus(self):
        from toffee.analog.analog_bundle import AnalogBundle
        from toffee.analog.analog_signal import AnalogStimulus
        sim = MockSimulator()
        bundle = AnalogBundle(sim)
        s = bundle.bind_stimulus("vinn", "VINN")
        assert isinstance(s, AnalogStimulus)
        assert bundle.vinn is s
        bundle.vinn.value = 1.8
        assert sim.sources["VINN"] == 1.8

    def test_bind_observation_creates_analog_observation(self):
        from toffee.analog.analog_bundle import AnalogBundle
        from toffee.analog.analog_signal import AnalogObservation
        sim = MockSimulator()
        sim._read_values["v(vout)"] = 2.3
        bundle = AnalogBundle(sim)
        s = bundle.bind_observation("vout", "v(vout)")
        assert isinstance(s, AnalogObservation)
        assert bundle.vout is s
        assert bundle.vout.voltage == 2.3


class TestAnalogObservation:
    def test_voltage_calls_read(self):
        from toffee.analog.analog_signal import AnalogObservation
        sim = MockSimulator()
        sim._read_values["v(vout)"] = 1.5
        obs = AnalogObservation("v(vout)", sim)
        assert obs.voltage == 1.5

    def test_accepts_spice_expressions(self):
        from toffee.analog.analog_signal import AnalogObservation
        sim = MockSimulator()
        sim._read_values["v(@m5[vdsat])"] = 0.3
        sim._read_values["i(@m1[id])"] = 10e-6
        obs_v = AnalogObservation("v(@m5[vdsat])", sim)
        obs_i = AnalogObservation("i(@m1[id])", sim)
        assert obs_v.voltage == 0.3
        assert obs_i.voltage == 10e-6
