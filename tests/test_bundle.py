import asyncio
import os

import pytest
import toffee
from toffee import *


class FakeXData: ...


class FakePin:
    def __init__(self):
        self.xdata, self.event, self.value, self.mIOType = FakeXData(), None, None, 0


class FakeDUT:
    def __init__(self):
        self.io_a = FakePin()
        self.io_b = FakePin()
        self.io_e = FakePin()
        self.io_c_1 = FakePin()
        self.io_c_2 = FakePin()
        self.io_c_3 = FakePin()
        self.io_c_4 = FakePin()
        self.io_d_1 = FakePin()
        self.io_d_2 = FakePin()
        self.io_d_3 = FakePin()

    def StepRis(*args, **kargs): ...


def test_bundle():
    toffee.setup_logging(log_level=toffee.logger.INFO)
    dut = FakeDUT()

    class BundleB(Bundle):
        signals = ["1", "2", "3"]

    class BundleA(Bundle):
        signals = ["a", "b", "e"]

        def __init__(self):
            super().__init__()
            self.c = BundleB.from_prefix(prefix="c_")
            self.d = BundleB.from_prefix(prefix="d_")

    bundle_1 = BundleA().set_prefix("io_").set_name("bundle_1").bind(dut)

    bundle_2 = BundleA.from_regex(regex="io_(.*)").bind(dut)

    print(bundle_2)

    bundle_3 = (
        BundleA.from_dict(
            {
                "a": "io_a",
                "b": "io_b",
                "e": "io_e",
                "c_1": "io_c_1",
                "c_2": "io_c_2",
                "c_3": "io_c_3",
                "d_1": "io_d_1",
                "d_2": "io_d_2",
                "d_3": "io_d_3",
            }
        )
        .set_name("bundle_3")
        .bind(dut)
    )

    bundle_1.assign({"a": 1, "b": 2, "c.1": 3, "c.2": 4}, multilevel=False)
    print(bundle_1.as_dict(multilevel=False))

    bundle_1.assign({"a": 5, "b": 6, "c": {"1": 7, "2": 8}}, multilevel=True)
    print(bundle_1.as_dict(multilevel=True))

    class BundleC(Bundle):
        signals = ["a", "b"]

        def __init__(self):
            super().__init__()
            self.c = Bundle.new_class_from_list(["1", "2", "3"]).from_prefix("c_")
            self.d = Bundle.new_class_from_list(["1", "2", "3"]).from_prefix("d_")

    bundle_4 = BundleC.from_prefix("io_").set_name("bundle_4").bind(dut)

    for signal in bundle_4.all_signals():
        print(signal)

    # bundle_4.set_all(666)
    print(bundle_4.as_dict())

    bundle_4.assign(
        {
            # "*": 777,
            "a": 1,
            "c": {
                "1": 3,
                # "*": 888,
            },
        },
        multilevel=True,
    )
    print(bundle_4.as_dict())

    class BundleD(Bundle):
        signals = ["a", "b"]

        def __init__(self):
            super().__init__()
            self.c = Bundle.new_class_from_list(["1", "2", "3", "4"]).from_dict(
                {"1": "c_1", "2": "c_2", "3": "c_3", "4": "c_4"}
            )

    bundle_5 = BundleD.from_prefix("io_").set_name("bundle_5").bind(dut)

    print(bundle_5.all_signals_rule())

    bundle_5.assign(
        {
            # "*": 999,
            "9": 1,
            "c.1": 4,
            "c.5.43": 3,
            "q": 4,
            "c": {
                "1": 3,
                "66": 4,
                # "*": 888,
            },
        },
        multilevel=True,
    )

    bundle_5.assign(
        {
            # "*": 999,
            "9": 1,
            "c.1": 4,
            "c.5.43": 3,
            "q": 4,
            "c": {
                "1": 3,
            },
        },
        multilevel=False,
    )


# Signal List Test


def test_signal_list():
    toffee.setup_logging(INFO)

    class MyDUT(FakeDUT):
        def __init__(self):
            self.io_a, self.io_b = FakePin(), FakePin()
            self.io_vec_0, self.io_vec_1, self.io_vec_2 = (
                FakePin(),
                FakePin(),
                FakePin(),
            )

    class BundleWithSignalList(Bundle):
        a, b = Signals(2)
        vec = SignalList("vec_#", 3)

    bundle = BundleWithSignalList.from_prefix("io_").set_name("bundle")
    bundle.bind(MyDUT())

    bundle.as_dict(multilevel=True)
    bundle.as_dict(multilevel=False)

    bundle.assign({"a": 1, "b": 2, "vec": [3, 4, 5]}, multilevel=True)
    bundle.assign({"a": 1, "b": 2, "vec": [3, 4, 5]}, multilevel=False)


def test_bundle_list():
    toffee.setup_logging(INFO)

    class MyDUT(FakeDUT):
        def __init__(self):
            super().__init__()
            self.io_c, self.io_d = FakePin(), FakePin()
            self.io_vec_0_a, self.io_vec_0_b, self.io_vec_1_a, self.io_vec_1_b = (
                FakePin(),
                FakePin(),
                FakePin(),
                FakePin(),
            )

    class SubBundle(Bundle):
        a, b = Signals(2)

    class BundleWithBundleList(Bundle):
        c, d = Signals(2)
        vec = BundleList(SubBundle, "vec_#_", 2)

    bundle = BundleWithBundleList.from_prefix("io_").set_name("bundle")
    bundle.bind(MyDUT())

    print(bundle)
    print(list(bundle.all_signals()))
    print(bundle.as_dict(multilevel=True))
    print(bundle.as_dict(multilevel=False))
    print(bundle.all_signals_rule())

    bundle.assign(
        {"c": 1, "d": 2, "vec": [{"a": 3, "b": 4}, {"a": 5, "b": 6}]}, multilevel=True
    )
    bundle.assign(
        {"c": 1, "d": 2, "vec": [{"a": 3, "b": 4}, {"a": 5, "b": 6}]}, multilevel=False
    )


# -------------------------------------------------------------------
# Bundle.bind() auto-detect loop.global_clock_event
# -------------------------------------------------------------------


class PinWithEvent:
    """A fake pin that carries an event, like a real picker XPin."""

    def __init__(self, event=None):
        self.xdata = FakeXData()
        self.event = event
        self.value = None
        self.mIOType = 0


class DUTWithEvents:
    """A fake DUT whose pins share a single clock event."""

    def __init__(self, clock_event):
        self.io_a = PinWithEvent(clock_event)
        self.io_b = PinWithEvent(clock_event)
        self.event = clock_event

    def StepRis(self, *args, **kwargs):
        pass


def _clean_loop():
    """Remove global_clock_event from the current event loop, if present."""
    loop = asyncio.get_event_loop()
    if hasattr(loop, "global_clock_event"):
        delattr(loop, "global_clock_event")


def test_bind_auto_detects_global_clock_event():
    """After start_clock(simulator), bundle.bind(dut) should auto-set
    __clock_event to the loop's global_clock_event.

    This is the mixed-signal scenario: the orchestrator's clock_event
    (set as global_clock_event) is different from the signal-level events.
    The bundle should prefer global_clock_event."""
    toffee.setup_logging(INFO)
    _clean_loop()

    # The orchestrator/simulator has its own clock_event
    orchestrator_event = asyncio.Event()
    # The DUT pins have a different (per-pin) event
    signal_event = asyncio.Event()

    # Simulate what start_clock(orchestrator) does
    loop = asyncio.get_event_loop()
    loop.global_clock_event = orchestrator_event

    dut = DUTWithEvents(signal_event)

    class SimpleBundle(Bundle):
        signals = ["a", "b"]

    bundle = SimpleBundle.from_prefix("io_").set_name("test_bundle")
    bundle.bind(dut)

    # The bundle should have auto-detected the global_clock_event,
    # NOT the signal-level event
    assert bundle._Bundle__clock_event is orchestrator_event, (
        "Bundle.bind() should auto-set __clock_event from loop.global_clock_event, "
        "not from signal.event"
    )

    _clean_loop()


def test_bind_pure_digital_no_global_still_works():
    """Pure-digital scenario: start_clock(raw_dut) + bind still works.
    When there is no global_clock_event on the loop, bind should fall back
    to the existing behaviour (pick up signal.event)."""
    toffee.setup_logging(INFO)
    _clean_loop()

    # No global_clock_event on the loop -- simulates a loop before start_clock
    clock_event = asyncio.Event()
    dut = DUTWithEvents(clock_event)

    class SimpleBundle(Bundle):
        signals = ["a", "b"]

    bundle = SimpleBundle.from_prefix("io_").set_name("test_bundle")
    bundle.bind(dut)

    # Should still get clock_event from the signal's event attribute
    assert bundle._Bundle__clock_event is clock_event, (
        "Pure-digital bind without global_clock_event should still pick up signal.event"
    )

    _clean_loop()


def test_set_clock_event_overrides_auto_detection():
    """Explicit set_clock_event() should override the auto-detected value."""
    toffee.setup_logging(INFO)
    _clean_loop()

    global_event = asyncio.Event()
    signal_event = asyncio.Event()

    # Simulate start_clock
    loop = asyncio.get_event_loop()
    loop.global_clock_event = global_event

    dut = DUTWithEvents(signal_event)

    class SimpleBundle(Bundle):
        signals = ["a", "b"]

    bundle = SimpleBundle.from_prefix("io_").set_name("test_bundle")
    bundle.bind(dut)

    # Auto-detection should have set it to global_event
    assert bundle._Bundle__clock_event is global_event

    # Explicit set_clock_event should override
    explicit_event = asyncio.Event()
    bundle.set_clock_event(explicit_event)
    assert bundle._Bundle__clock_event is explicit_event, (
        "Explicit set_clock_event() should override auto-detected value"
    )

    _clean_loop()


def test_missing_signal_raises_on_bind():
    """Binding a bundle that references a non-existent DUT signal must raise."""

    class SmallBundle(Bundle):
        signals = ["x"]

    class TinyDUT:
        def __init__(self):
            self.io_y = FakePin()

    with pytest.raises(Exception):
        SmallBundle.from_prefix("io_").bind(TinyDUT())
