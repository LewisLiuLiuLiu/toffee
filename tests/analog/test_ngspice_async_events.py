import pytest
from toffee.analog.ngspice_simulator import NgSpiceSimulator


def test_add_async_trigger_api():
    # We can't easily run a real transient without libngspice installed,
    # but we can verify the API surface and internal state.
    sim = NgSpiceSimulator.__new__(NgSpiceSimulator)
    sim._async_triggers = {}
    sim._trigger_lock = __import__("threading").Lock()

    sim.add_async_trigger("V(out)", threshold=1.5)
    assert "V(out)" in sim._async_triggers
    assert sim._async_triggers["V(out)"]["armed"] is True

    sim.remove_async_trigger("V(out)")
    assert "V(out)" not in sim._async_triggers


def test_send_data_fires_trigger():
    sim = NgSpiceSimulator.__new__(NgSpiceSimulator)
    sim._async_triggers = {}
    sim._trigger_lock = __import__("threading").Lock()
    sim._node_voltages = {}
    sim._spice_time = 5e-9
    sim._next_sync_time = float("inf")

    sim.add_async_trigger("v(out)", threshold=1.5)

    import ctypes
    from toffee.analog.ngspice_simulator import _VecValues, _VecValuesAll

    vv = _VecValues(name=b"v(out)", creal=1.6, cimag=0.0, is_scale=False, is_complex=False)
    p_vv = ctypes.pointer(ctypes.pointer(vv))
    vva = _VecValuesAll(veccount=1, vecindex=0, vecsa=p_vv)

    sim._on_send_data(ctypes.pointer(vva), 1, 0, None)

    assert sim._async_triggers["v(out)"]["armed"] is False
    assert sim._next_sync_time == 5e-9
    assert sim._node_voltages["v(out)"] == 1.6
