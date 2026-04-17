"""Analog agent for toffee."""

from ..agent import Agent


class AnalogAgent(Agent):
    """Agent that uses a Simulator's clock_event.wait as its time step."""

    def __init__(self, bundle=None, simulator=None):
        if simulator is not None:
            # Agent.__init__ accepts a callable as monitor_step
            super().__init__(simulator.clock_event.wait)
            self.simulator = simulator
        else:
            super().__init__(bundle)
