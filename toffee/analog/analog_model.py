"""Analog model base class for toffee."""

from ..model import Model


_AUTO_COMPARE_DEFAULT = True


def auto_compare_default() -> bool:
    """Return the default value for the ``auto_compare`` hook flag."""
    return _AUTO_COMPARE_DEFAULT


class AnalogModel(Model):
    """Reference model for analog/mixed-signal verification.

    Extends :class:`Model` with a :meth:`predict` convenience method
    for time-based analog predictions (RC charging curves, opamp gain
    over time, etc.), and a :meth:`check` method for complex validations
    (eye diagrams, statistical analysis).
    """

    def predict(self, t: float) -> float:
        """Return predicted value at simulation time *t*.

        Override in subclasses.  The default raises :exc:`NotImplementedError`.
        """
        raise NotImplementedError(
            f"{type(self).__name__}.predict() not implemented"
        )

    def check(self) -> bool:
        """Return pass/fail verdict after simulation completes.

        Override for complex checks (eye diagrams, settling time, etc.).
        The framework calls this automatically after the Monitor loop
        completes.  Default returns ``True`` (pass).
        """
        return True
