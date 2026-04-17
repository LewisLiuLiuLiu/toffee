from typing import Iterator


class StepExactStrategy:
    """Subdivides a large analog time leap into smaller substeps.

    This mitigates the lack of async event support in Xyce by bounding
    the maximum latency between analog threshold checks.
    """

    def __init__(self, max_step: float = 1e-9):
        self.max_step = max_step

    def iter_steps(self, current: float, target: float) -> Iterator[float]:
        if target <= current:
            return
        while current + self.max_step < target:
            current += self.max_step
            yield current
        yield target
