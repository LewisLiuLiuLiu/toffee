"""Tests for XyceSimulator PortMapping injection + read() YADC transparency.

All tests use __new__() to bypass __init__ (which calls xyce_interface())
so that no real Xyce shared library is needed.
"""

import asyncio
import os
import tempfile
from unittest.mock import MagicMock

import pytest
import toffee_test
from toffee.analog.xyce_simulator import XyceSimulator
from toffee.mixed_signal.port_mapping import PortMapping, PortDirection


class FakeXyceInterface:
    """Minimal fake xyce_interface for testing XyceSimulator methods."""

    def __init__(self, libdir=None):
        self._libdir = libdir
        self._sim_time = 0.0

    def initialize(self, args):
        return 1

    def getSimTime(self):
        return self._sim_time

    def setPauseTime(self, pause_time):
        return 1

    def simulateUntil(self, time):
        self._sim_time = time
        return (1, time)

    def obtainResponse(self, variable_name):
        return (0, 0.5)

    def getTimeStatePairsADC(self):
        return (
            ("YADC1", "YADC2"),
            ((0.0, 0), (1e-9, 1)),
            ((0.0, 0), (1e-9, 0)),
        )

    def getADCMap(self):
        return (("YADC1", 0), ("YADC2", 1))

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
    sim._prev_adc_states = {}
    sim._original_netlist = ""
    sim._netlist_path = ""
    sim._temp_dir = None
    sim._yadc_to_node = {}
    sim._yadc_overrides = {}
    sim._vdd = 1.8
    return sim


# ---------------------------------------------------------------------------
# Cycle 1: read() returns YADC quantized voltage for nodes in _yadc_overrides
# ---------------------------------------------------------------------------


@toffee_test.testcase
async def test_read_returns_yadc_override_voltage():
    """read() should return the YADC quantized voltage for nodes in _yadc_overrides.

    When _yadc_overrides contains an entry for a variable, read() should
    return that override value directly instead of calling obtainResponse.
    """
    sim = _make_sim()
    sim._yadc_overrides = {"V(out)": 1.8, "V(cmp)": 0.0}

    assert sim.read("V(out)") == 1.8
    assert sim.read("V(cmp)") == 0.0


# ---------------------------------------------------------------------------
# Cycle 2: read() falls through to existing logic for non-YADC nodes
# ---------------------------------------------------------------------------


@toffee_test.testcase
async def test_read_falls_through_to_obtainResponse_for_non_yadc_nodes():
    """read() should call obtainResponse when the variable is not in _yadc_overrides.

    When _yadc_overrides is empty or does not contain the requested variable,
    read() should fall through to the existing obtainResponse path.
    """
    sim = _make_sim()
    sim._yadc_overrides = {}

    # obtainResponse returns (status, value); status != 0 means success
    sim._xyce.obtainResponse = MagicMock(return_value=(1, 2.5))

    result = sim.read("V(other)")
    assert result == 2.5
    sim._xyce.obtainResponse.assert_called_once_with("V(other)")


# ---------------------------------------------------------------------------
# Cycle 3: next_event() populates _yadc_overrides after simulateUntil
# ---------------------------------------------------------------------------


@toffee_test.testcase
async def test_next_event_populates_yadc_overrides():
    """next_event() should populate _yadc_overrides from read_adc_states().

    After simulateUntil completes, next_event should read ADC states,
    translate them through _yadc_to_node mapping, and store quantized
    voltages in _yadc_overrides. State >= 1 → VDD, state == 0 → 0.0.
    """
    sim = _make_sim()
    sim._yadc_to_node = {"YADC1": "V(out)", "YADC2": "V(cmp)"}
    sim._yadc_overrides = {}

    # FakeXyceInterface.getTimeStatePairsADC returns:
    #   YADC1 state=1, YADC2 state=0
    await sim.next_event(target_time=1e-9)

    # YADC1 state=1 → VDD=1.8, YADC2 state=0 → 0.0
    assert sim._yadc_overrides["V(out)"] == 1.8
    assert sim._yadc_overrides["V(cmp)"] == 0.0


# ---------------------------------------------------------------------------
# Cycle 4: __init__ builds _yadc_to_node from PortMapping
# ---------------------------------------------------------------------------


@toffee_test.testcase
async def test_init_builds_yadc_to_node_from_port_mapping():
    """_build_yadc_to_node() should map yadc_device → analog node name.

    Given a PortMapping with a2d entries that have yadc_device set,
    the method should build _yadc_to_node dict mapping yadc_device
    name to the analog node name (V() wrapped).
    """
    pm = PortMapping()
    pm.add_digital("cmp_out")
    pm.add_analog("out")
    pm.a2d("out", "cmp_out", yadc_device="YADC1")

    # Use __new__() to bypass __init__, then call _build_yadc_to_node directly
    sim = XyceSimulator.__new__(XyceSimulator)
    sim._yadc_to_node = {}
    sim._yadc_overrides = {}
    sim._vdd = 1.8
    sim._build_yadc_to_node(pm)

    assert sim._yadc_to_node == {"YADC1": "out"}


# ---------------------------------------------------------------------------
# Cycle 5: _inject_ydac_yadc injects YDAC/YADC lines before .end
# ---------------------------------------------------------------------------


@toffee_test.testcase
async def test_inject_ydac_yadc_into_netlist():
    """_inject_ydac_yadc should insert YDAC and YADC lines before .end.

    Given a netlist with an .end directive and a PortMapping with d2a and
    a2d entries, the method should create a modified netlist that contains
    YDAC lines (one per d2a entry) and YADC lines (one per a2d entry with
    yadc_device set) inserted before .end.
    """
    # Create a temporary netlist file
    tmpdir = tempfile.mkdtemp(prefix="toffee_test_xyce_")
    netlist_path = os.path.join(tmpdir, "test.cir")
    with open(netlist_path, "w") as f:
        f.write("R1 in out 1k\n.end\n")

    pm = PortMapping()
    pm.add_digital("dac_in")
    pm.add_analog("in")
    pm.d2a("dac_in", "in")
    pm.add_digital("cmp_out")
    pm.add_analog("out")
    pm.a2d("out", "cmp_out", yadc_device="YADC1")

    # Use __new__() and call _inject_ydac_yadc directly
    sim = XyceSimulator.__new__(XyceSimulator)
    sim._temp_dir = tmpdir

    modified_path = sim._inject_ydac_yadc(netlist_path, pm)

    # Read the modified netlist and verify injection
    with open(modified_path, "r") as f:
        content = f.read()

    # Should contain YDAC line for d2a entry (using analog port name)
    assert "ydac in in 0" in content
    # Should contain YADC line for a2d entry (using yadc_device name)
    assert "yadc YADC1 out 0" in content
    # .end should still be present
    assert ".end" in content
    # Original line should still be present
    assert "R1 in out 1k" in content

    # Cleanup
    import shutil
    shutil.rmtree(tmpdir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Cycle 6: Backward compatibility - no port_mapping means no injection
# ---------------------------------------------------------------------------


@toffee_test.testcase
async def test_no_port_mapping_means_empty_yadc_structures():
    """Without port_mapping, _yadc_to_node and _yadc_overrides should be empty.

    When XyceSimulator is created without port_mapping, the YADC-related
    attributes should be initialized to empty dicts, ensuring read() and
    next_event() behave identically to the pre-PortMapping era.
    """
    sim = _make_sim()
    assert sim._yadc_to_node == {}
    assert sim._yadc_overrides == {}
    assert sim._vdd == 1.8

    # read() should fall through to obtainResponse when _yadc_overrides is empty
    sim._xyce.obtainResponse = MagicMock(return_value=(1, 3.3))
    result = sim.read("V(test)")
    assert result == 3.3
    sim._xyce.obtainResponse.assert_called_once_with("V(test)")
