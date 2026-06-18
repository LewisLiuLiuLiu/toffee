"""Analog environment for toffee."""

from ..env import Env


class AnalogEnv(Env):
    """Top-level container for analog verification."""

    def __init__(self, simulator):
        super().__init__()
        self.simulator = simulator

    def finish(self):
        self.simulator.finish()
