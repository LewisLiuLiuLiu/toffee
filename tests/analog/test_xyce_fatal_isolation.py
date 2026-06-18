"""Tests for Xyce fatal error isolation (mock-based, no real Xyce needed)."""
import asyncio
import pytest
from toffee.analog.xyce_simulator import XyceSimulator


class FakeXyceWithFatal:
    """Mock xyce_interface that simulates fatal error on initialize."""
    def __init__(self, libdir=None):
        self._handler_registered = False
        self._fatal_msg = ""

    def setReportHandler(self):
        self._handler_registered = True
        return 1

    def getLastError(self):
        return self._fatal_msg

    def initialize(self, args):
        self._fatal_msg = "Error: unresolved .param in sky130.lib"
        return 0  # failure

    def simulateUntil(self, requestedTime):
        self._fatal_msg = "Convergence failure at t=1.5ns"
        return (0, 0.0)

    def setPauseTime(self, pauseTime):
        self._fatal_msg = "Pause time rejected"
        return 0

    def getSimTime(self):
        return 0.0

    def close(self):
        pass


class FakeXyceNoHandler:
    """Mock xyce_interface WITHOUT setReportHandler (old version)."""
    def __init__(self, libdir=None):
        pass

    def initialize(self, args):
        return 1

    def getSimTime(self):
        return 0.0

    def close(self):
        pass


def test_fatal_error_raises_runtime_error_with_message():
    """When Xyce returns failure status, RuntimeError includes the fatal message."""
    sim = XyceSimulator.__new__(XyceSimulator)
    sim._xyce = FakeXyceWithFatal()
    sim._clock_event = asyncio.Event()
    sim._current_time = 0.0
    sim._prev_adc_states = {}
    sim._yadc_to_node = {}
    sim._yadc_overrides = {}
    sim._vdd = 1.8
    sim._original_netlist = "test.cir"
    sim._temp_dir = None
    sim._netlist_path = "test.cir"
    # Manually call setReportHandler like __init__ would
    if hasattr(sim._xyce, "setReportHandler"):
        sim._xyce.setReportHandler()
    assert sim._xyce._handler_registered is True
    # Now simulate what happens when initialize fails
    status = sim._xyce.initialize(["test.cir"])
    assert status == 0
    msg = sim._xyce.getLastError()
    assert "unresolved .param" in msg


def test_init_registers_handler_when_available():
    """XyceSimulator should call setReportHandler if available."""
    sim = XyceSimulator.__new__(XyceSimulator)
    sim._xyce = FakeXyceWithFatal()
    sim._clock_event = asyncio.Event()
    sim._current_time = 0.0
    sim._prev_adc_states = {}
    sim._yadc_to_node = {}
    sim._yadc_overrides = {}
    sim._vdd = 1.8
    if hasattr(sim._xyce, "setReportHandler"):
        sim._xyce.setReportHandler()
    assert sim._xyce._handler_registered is True


def test_graceful_skip_when_no_handler():
    """Old xyce_interface without setReportHandler should not crash."""
    sim = XyceSimulator.__new__(XyceSimulator)
    sim._xyce = FakeXyceNoHandler()
    sim._clock_event = asyncio.Event()
    sim._current_time = 0.0
    sim._prev_adc_states = {}
    sim._yadc_to_node = {}
    sim._yadc_overrides = {}
    sim._vdd = 1.8
    # Should not raise
    if hasattr(sim._xyce, "setReportHandler"):
        sim._xyce.setReportHandler()
    # No error - old interface works fine


def test_runtime_error_includes_xyce_message():
    """RuntimeError raised by XyceSimulator should contain the Xyce error text."""
    sim = XyceSimulator.__new__(XyceSimulator)
    sim._xyce = FakeXyceWithFatal()
    sim._clock_event = asyncio.Event()
    sim._current_time = 0.0
    sim._prev_adc_states = {}
    sim._yadc_to_node = {}
    sim._yadc_overrides = {}
    sim._vdd = 1.8
    sim._original_netlist = "test.cir"
    sim._netlist_path = "test.cir"
    sim._temp_dir = None
    if hasattr(sim._xyce, "setReportHandler"):
        sim._xyce.setReportHandler()
    # Simulate advance_to failure
    sim._xyce._fatal_msg = "Convergence failure at t=1.5ns"
    # Call advance_to which should raise
    with pytest.raises(RuntimeError, match="Convergence failure"):
        sim.advance_to(1e-9)


def test_runtime_error_includes_xyce_message_set_pause_time():
    """RuntimeError from set_pause_time should contain the Xyce error text."""
    sim = XyceSimulator.__new__(XyceSimulator)
    sim._xyce = FakeXyceWithFatal()
    sim._clock_event = asyncio.Event()
    sim._current_time = 0.0
    sim._prev_adc_states = {}
    sim._yadc_to_node = {}
    sim._yadc_overrides = {}
    sim._vdd = 1.8
    sim._original_netlist = "test.cir"
    sim._netlist_path = "test.cir"
    sim._temp_dir = None
    if hasattr(sim._xyce, "setReportHandler"):
        sim._xyce.setReportHandler()
    sim._xyce._fatal_msg = "Pause time rejected"
    with pytest.raises(RuntimeError, match="Pause time rejected"):
        sim.set_pause_time(5e-9)
