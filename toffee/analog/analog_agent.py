"""Analog agent for toffee."""

from .._base_agent import Driver, Monitor
from ..agent import Agent


class AnalogDriver(Driver):
    """Driver subclass for analog/mixed-signal Agents.

    Currently inherits all behavior from :class:`Driver`. Exists as a
    distinct class to provide an extension point for future analog-specific
    driver logic (e.g., waveform-aware driving, multi-node stimulus
    coordination) without modifying the base :class:`Driver`.

    The background callback loop in :class:`AnalogEnv` (via
    ``start_callback_executor``) ensures priority tasks are executed
    without ``start_clock``.
    """


class AnalogMonitor(Monitor):
    """Monitor subclass for analog/mixed-signal Agents.

    Currently inherits all behavior from :class:`Monitor`. Exists as a
    distinct class to provide an extension point for future analog-specific
    monitoring logic (e.g., DC/AC vs Transient mode, waveform capture,
    trigger-based sampling) without modifying the base :class:`Monitor`.

    Inherits the full asynchronous observation pipeline from
    :class:`Monitor`.
    """


class AnalogAgent(Agent):
    """Agent that uses a Simulator event as its time step.

    By default uses ``clock_event`` (the "step" event).  Pass
    ``event_name`` to wait on a different named event from the
    simulator's ``events`` dict (e.g. ``"threshold_crossed"``).

    ``compare_func`` is an optional comparison function used by
    the model comparison pipeline (see :func:`toffee._compare.tolerance_compare`).
    """

    def __init__(self, bundle=None, simulator=None, event_name="step", compare_func=None):
        if simulator is not None:
            event = simulator.events.get(event_name, simulator.clock_event)
            super().__init__(event.wait)
            self.simulator = simulator
            self._event_name = event_name
        else:
            super().__init__(bundle)
            self._event_name = event_name
        self._compare_func = compare_func
        if compare_func is not None:
            for driver in self.drivers.values():
                driver.compare_func = compare_func

    def __create_all_drivers(self):
        for driver_method in self.all_driver_method():
            driver = AnalogDriver(driver_method.__original_func__)
            self.drivers[driver_method.__name__] = driver

    def __create_all_monitors(self):
        for monitor_method in self.all_monitor_method():
            monitor = AnalogMonitor(self, monitor_method.__original_func__)
            self.monitors[monitor_method.__name__] = monitor
