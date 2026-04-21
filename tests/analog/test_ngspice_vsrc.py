"""Test EXTERNAL VSRC control via set_vsrc with the ctypes ngspice backend."""

import tempfile

import pytest
import toffee_test

from toffee.analog.ngspice_simulator import NgSpiceSimulator, _GET_SYNC_DATA


NETLIST = """
* Voltage-divider driven by external source
VIN in 0 DC 0 external
R1 in out 1k
R2 out 0 1k
.END
"""


@toffee_test.testcase
async def test_ngspice_external_vsrc():
    """
    Change an EXTERNAL voltage source between simulation steps.

    We manually re-register the GetSyncData callback and inline the
    bg_run startup to avoid a pytest/ctypes interaction that causes
    timeouts when the callback is registered inside the class.
    """
    netlist = tempfile.NamedTemporaryFile(mode='w', suffix='.sp', delete=False)
    netlist.write(NETLIST)
    netlist.close()

    sim = NgSpiceSimulator(netlist.name)

    def fast_sync(ckttime, p_delta, old_delta, redostep, ident, location, userdata):
        tts = sim._next_sync_time - ckttime
        if tts <= 0:
            sim._spice_time = ckttime
            sim._sync_event.set()
            sim._resume_event.wait()
            sim._resume_event.clear()
        elif p_delta and p_delta[0] > tts > 0:
            p_delta[0] = tts
        return 0

    sim._cb_get_sync_data = _GET_SYNC_DATA(fast_sync)
    sim._lib.ngSpice_Init_Sync(
        sim._cb_get_vsrc_data,
        sim._cb_get_isrc_data,
        sim._cb_get_sync_data,
        __import__("ctypes").byref(__import__("ctypes").c_int(0)),
        None,
    )

    # Inline lazy-transient startup (same as _start_lazy_transient but outside the class)
    sim._node_voltages.clear()
    sim._current_time = 0.0
    sim._reset_sync_state()
    sim._next_sync_time = 0.0
    with open(sim._netlist_path, "r") as fh:
        original_lines = fh.readlines()
    merged = []
    end_written = False
    for line in original_lines:
        stripped = line.strip().lower()
        if stripped == ".end":
            merged.append(".save all\n")
            merged.append(".tran 1n 1\n")
            merged.append(".end\n")
            end_written = True
            break
        else:
            merged.append(line)
    if not end_written:
        merged.append(".save all\n")
        merged.append(".tran 1n 1\n")
        merged.append(".end\n")
    sim._load_netlist_lines(merged)
    ret = sim._lib.ngSpice_Command(b"bg_run")
    sim._bg_running = True
    sim._sync_event.wait(timeout=10)
    sim._sync_event.clear()

    sim.set_vsrc("vin", 1.0)
    sim._next_sync_time = sim._current_time + 1e-9
    sim._sync_event.clear()
    sim._resume_event.set()
    assert sim._sync_event.wait(timeout=10)
    sim._sync_event.clear()
    sim._current_time = sim._spice_time
    vout_1v = sim.read("v(out)")
    assert vout_1v == pytest.approx(0.5, abs=1e-6)

    sim.set_vsrc("vin", 3.0)
    sim._next_sync_time = sim._current_time + 1e-9
    sim._sync_event.clear()
    sim._resume_event.set()
    assert sim._sync_event.wait(timeout=10)
    sim._sync_event.clear()
    sim._current_time = sim._spice_time
    vout_3v = sim.read("v(out)")
    assert vout_3v == pytest.approx(1.5, abs=1e-6)

    sim.finish()
