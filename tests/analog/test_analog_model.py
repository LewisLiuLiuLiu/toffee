"""Tests for AnalogModel — predict() and auto_compare=True hooks."""
import asyncio
import pytest
from toffee.analog.analog_model import AnalogModel


class TestAnalogModelPredict:
    @pytest.mark.asyncio
    async def test_predict_is_callable(self):
        class RCModel(AnalogModel):
            def predict(self, t):
                return 1.8 * (1 - 2.718 ** (-t / 1e-9))

        model = RCModel()
        v = model.predict(1e-9)
        assert 1.0 < v < 1.2, f"Expected ~1.14V, got {v}"

    @pytest.mark.asyncio
    async def test_predict_default_raises(self):
        class DefaultModel(AnalogModel):
            pass
        model = DefaultModel()
        with pytest.raises(NotImplementedError):
            model.predict(1e-9)
