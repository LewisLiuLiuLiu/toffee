"""Analog agent for toffee."""

from ..agent import Agent


class AnalogAgent(Agent):
    """Agent that uses a Simulator event as its time step.

    By default uses ``clock_event`` (the "step" event).  Pass
    ``event_name`` to wait on a different named event from the
    simulator's ``events`` dict (e.g. ``"threshold_crossed"``).
    """

    def __init__(self, bundle=None, simulator=None, event_name="step"):
        if simulator is not None:
            event = simulator.events.get(event_name, simulator.clock_event)
            super().__init__(event.wait)
            self.simulator = simulator
            self._event_name = event_name
        else:
            super().__init__(bundle)
            self._event_name = event_name
