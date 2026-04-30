"""Test lazy-sync transient stepping with the ctypes ngspice backend."""

import tempfile

import toffee_test
from toffee.analog.ngspice_simulator import NgSpiceSimulator


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

    With the singleton callback model, the global GetSyncData callback
    handles lazy sync automatically — no manual re-registration needed.
    """
    netlist = tempfile.NamedTemporaryFile(mode='w', suffix='.sp', delete=False)
    netlist.write(NETLIST)
    netlist.close()

    sim = NgSpiceSimulator(netlist.name)

    sim.step_time(1e-9)
    assert sim._current_time > 0
    vout = sim.read("v(out)")
    assert isinstance(vout, float)
    assert vout > 0
    sim.finish()
