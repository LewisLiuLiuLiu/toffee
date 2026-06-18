"""Tests for AnalogBackend ABC."""
import abc
import pytest

from toffee.analog.analog_backend import AnalogBackend


class TestAnalogBackendABC:
    """Verify the AnalogBackend ABC contract."""

    def test_abc_exists_and_is_abstract(self):
        assert issubclass(AnalogBackend, abc.ABC)

    def test_abstract_methods_declared(self):
        expected = {
            "set_source",
            "set_parameter",
            "read",
            "register_trigger",
            "unregister_trigger",
            "finish",
        }
        # set_source_waveform and read_adc_states have defaults,
        # so they are not in __abstractmethods__
        actual = set(AnalogBackend.__abstractmethods__)
        assert actual == expected, f"Expected {expected}, got {actual}"

    def test_default_read_adc_states_returns_empty(self):
        class Minimal(AnalogBackend):
            def set_source(self, n, v): pass
            def set_source_waveform(self, n, t, v): pass
            def set_parameter(self, n, v): pass
            def read(self, n):
                return 0.0
            def register_trigger(self, n, t): pass
            def unregister_trigger(self, n): pass
            def finish(self): pass

        backend = Minimal()
        assert backend.read_adc_states() == {}

    def test_default_set_source_waveform_raises(self):
        class Minimal(AnalogBackend):
            def set_source(self, n, v): pass
            def set_parameter(self, n, v): pass
            def read(self, n):
                return 0.0
            def read_adc_states(self):
                return {}
            def register_trigger(self, n, t): pass
            def unregister_trigger(self, n): pass
            def finish(self): pass

        backend = Minimal()
        with pytest.raises(NotImplementedError):
            backend.set_source_waveform("v", [0], [1])


class TestNgSpiceBackend:
    """Verify NgSpiceSimulator satisfies the AnalogBackend contract."""

    def test_is_subclass(self):
        from toffee.analog.ngspice_simulator import NgSpiceSimulator
        assert issubclass(NgSpiceSimulator, AnalogBackend)

    def test_not_abstract(self):
        """All abstract methods must be implemented — no __abstractmethods__."""
        from toffee.analog.ngspice_simulator import NgSpiceSimulator
        assert not hasattr(NgSpiceSimulator, "__abstractmethods__") or \
            len(NgSpiceSimulator.__abstractmethods__) == 0

    def test_methods_exist(self):
        from toffee.analog.ngspice_simulator import NgSpiceSimulator
        for name in ("set_source", "set_parameter", "read",
                     "read_adc_states", "register_trigger",
                     "unregister_trigger", "finish"):
            assert hasattr(NgSpiceSimulator, name), \
                f"NgSpiceSimulator missing method: {name}"

    def test_ngspice_keeps_default_set_source_waveform(self):
        """ngspice does not override set_source_waveform — uses ABC default (raises)."""
        from toffee.analog.ngspice_simulator import NgSpiceSimulator
        assert NgSpiceSimulator.set_source_waveform is AnalogBackend.set_source_waveform


class TestXyceBackend:
    """Verify XyceSimulator satisfies the AnalogBackend contract."""

    @pytest.fixture(autouse=True)
    def _skip_if_no_xyce(self):
        try:
            import xyce_interface  # noqa: F401
        except ImportError:
            pytest.skip("xyce_interface not available")

    def test_is_subclass(self):
        from toffee.analog.xyce_simulator import XyceSimulator
        assert issubclass(XyceSimulator, AnalogBackend)

    def test_not_abstract(self):
        from toffee.analog.xyce_simulator import XyceSimulator
        assert not hasattr(XyceSimulator, "__abstractmethods__") or \
            len(XyceSimulator.__abstractmethods__) == 0

    def test_methods_exist(self):
        from toffee.analog.xyce_simulator import XyceSimulator
        for name in ("set_source", "set_source_waveform", "set_parameter",
                     "read", "read_adc_states", "register_trigger",
                     "unregister_trigger", "finish"):
            assert hasattr(XyceSimulator, name), \
                f"XyceSimulator missing method: {name}"
