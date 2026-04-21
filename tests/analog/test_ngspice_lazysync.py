"""Test lazy-sync transient stepping with the ctypes ngspice backend."""

import tempfile

import toffee_test
from toffee.analog.ngspice_simulator import NgSpiceSimulator, _GET_SYNC_DATA


NETLIST = """
* RC circuit for lazy sync test
VIN in 0 DC 1
R1 in out 1k
C1 out 0 1p
.END
"""


@toffee_test.testcase
async def test_lazysync_step_time():
    """
    Step a transient simulation by 1 ns.

    We manually re-register the GetSyncData callback here because
    pytest's trace/profiling machinery introduces severe overhead
    (or even correctness issues) when the callback is registered
    inside the NgSpiceSimulator class definition.  Re-registering
    from the test function scope avoids both problems.
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

    sim.step_time(1e-9)
    assert sim._current_time > 0
    vout = sim.read("v(out)")
    assert isinstance(vout, float)
    assert vout > 0
    sim.finish()
