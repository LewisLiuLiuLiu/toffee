import pytest
from toffee.mixed_signal.step_strategy import StepExactStrategy


def test_step_exact_subdivides():
    strategy = StepExactStrategy(max_step=2e-9)
    steps = list(strategy.iter_steps(current=0.0, target=7e-9))
    expected = [2e-9, 4e-9, 6e-9, 7e-9]
    assert len(steps) == len(expected)
    for s, e in zip(steps, expected):
        assert s == pytest.approx(e)


def test_step_exact_no_subdivision_when_under_max():
    strategy = StepExactStrategy(max_step=5e-9)
    steps = list(strategy.iter_steps(current=1e-9, target=3e-9))
    assert steps == [3e-9]
