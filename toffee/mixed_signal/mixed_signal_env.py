"""Mixed-signal environment for toffee."""

from ..env import Env


class MixedSignalEnv(Env):
    """Top-level container for mixed-signal verification.

    Holds a :class:`MixedSignalOrchestrator` which coordinates analog and
    digital domains.  Use with ``start_clock(orchestrator)`` — the
    orchestrator's ``next_event()`` drives time advancement for both domains.
    """

    def __init__(self, orchestrator):
        super().__init__()
        self.orchestrator = orchestrator

    def finish(self):
        self.orchestrator.finish()
