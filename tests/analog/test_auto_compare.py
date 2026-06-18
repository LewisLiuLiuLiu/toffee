"""Tests for auto_compare=False and Model.check()."""
import asyncio
import pytest
from toffee.analog.analog_model import AnalogModel


class TestAnalogModelCheck:
    @pytest.mark.asyncio
    async def test_check_default_returns_true(self):
        class MyModel(AnalogModel):
            pass
        model = MyModel()
        assert model.check() is True

    @pytest.mark.asyncio
    async def test_check_overridden(self):
        class FailModel(AnalogModel):
            def check(self):
                return False
        model = FailModel()
        assert model.check() is False


class TestAutoCompareFlag:
    def test_auto_compare_defaults_to_true(self):
        """Hook auto_compare metadata defaults to True."""
        from toffee.analog.analog_model import auto_compare_default
        assert auto_compare_default() is True
