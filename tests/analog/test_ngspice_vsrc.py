"""Test EXTERNAL VSRC control via set_vsrc with the ctypes ngspice backend."""

import tempfile

import pytest
import toffee_test

from toffee.analog.ngspice_simulator import NgSpiceSimulator


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

    With the singleton callback model, the global callbacks handle lazy
    sync and VSRC data automatically — no manual re-registration needed.
    """
    netlist = tempfile.NamedTemporaryFile(mode='w', suffix='.sp', delete=False)
    netlist.write(NETLIST)
    netlist.close()

    sim = NgSpiceSimulator(netlist.name)

    # Drive VIN=1V and step
    sim.set_vsrc("vin", 1.0)
    sim.step_time(1e-9)
    vout_1v = sim.read("v(out)")
    assert vout_1v == pytest.approx(0.5, abs=1e-6)

    # Change to VIN=3V and step
    sim.set_vsrc("vin", 3.0)
    sim.step_time(1e-9)
    vout_3v = sim.read("v(out)")
    assert vout_3v == pytest.approx(1.5, abs=1e-6)

    sim.finish()
