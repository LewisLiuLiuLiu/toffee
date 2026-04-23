"""Tests for XyceSimulator.set_pause_time, read_adc_states, and get_adc_map.

These tests use a fake xyce_interface so they do not require the real Xyce
shared library.  The fake is injected directly into the simulator instance
via __new__() to avoid polluting sys.modules.
"""

import asyncio
from unittest.mock import MagicMock

import pytest
import toffee_test
from toffee.analog.xyce_simulator import XyceSimulator


class FakeXyceInterface:
    """Minimal fake xyce_interface for testing XyceSimulator methods."""

    def __init__(self, libdir=None):
        self._libdir = libdir

    def initialize(self, args):
        return 1

    def setPauseTime(self, pause_time):
        return 1

    def getTimeStatePairsADC(self):
        return (
            ("ADC1", "ADC2"),
            ((0.0, 0), (1e-9, 1)),
            ((0.0, 0), (1e-9, 0)),
        )

    def getADCMap(self):
        return (("ADC1", 0), ("ADC2", 1))

    def close(self):
        pass


def _make_sim():
    """Create an XyceSimulator stub backed by a FakeXyceInterface.

    Uses __new__() to bypass __init__ (which calls xyce_interface() and
    initialize()) so that no real Xyce library is needed.
    """
    sim = XyceSimulator.__new__(XyceSimulator)
    sim._xyce = FakeXyceInterface()
    sim._clock_event = asyncio.Event()
    sim._current_time = 0.0
    sim._original_netlist = ""
    sim._netlist_path = ""
    sim._temp_dir = None
    return sim


@toffee_test.testcase
async def test_set_pause_time_success():
    """set_pause_time should call _xyce.setPauseTime and succeed when it returns 1."""
    sim = _make_sim()
    # Default fake returns 1, so this should succeed without raising
    sim.set_pause_time(5e-9)


@toffee_test.testcase
async def test_set_pause_time_failure():
    """set_pause_time should raise RuntimeError when _xyce.setPauseTime returns 0."""
    sim = _make_sim()
    sim._xyce.setPauseTime = MagicMock(return_value=0)

    with pytest.raises(RuntimeError, match="setPauseTime"):
        sim.set_pause_time(5e-9)


@toffee_test.testcase
async def test_read_adc_states():
    """read_adc_states should return a dict mapping ADC name to latest state."""
    sim = _make_sim()

    result = sim.read_adc_states()

    assert isinstance(result, dict)
    assert "ADC1" in result
    assert "ADC2" in result
    # Latest state for ADC1 is the last entry in its time-state pairs
    assert result["ADC1"] == 1
    assert result["ADC2"] == 0


@toffee_test.testcase
async def test_read_adc_states_returns_empty_on_error():
    """read_adc_states should return {} when _xyce.getTimeStatePairsADC raises."""
    sim = _make_sim()
    sim._xyce.getTimeStatePairsADC = MagicMock(side_effect=Exception("fail"))

    result = sim.read_adc_states()

    assert result == {}


@toffee_test.testcase
async def test_get_adc_map():
    """get_adc_map should return the result from _xyce.getADCMap()."""
    sim = _make_sim()

    result = sim.get_adc_map()

    assert result == (("ADC1", 0), ("ADC2", 1))
