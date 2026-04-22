# Xyce Mixed-Signal Simulator Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a `MixedSignalSimulator` layer on top of Xyce that enables seamless digital→analog bridging (via `updateTimeVoltagePairs` and `setCircuitParameter`) and solves analog→digital precision via a configurable Step-Exact strategy.

**Architecture:** Introduce a `mixed_signal` package with `MixedSignalSimulator` (orchestrates Xyce + digital DUT), `PortMapping` / `BridgeMap` (declares which digital pins drive which analog DACs / parameters), and `StepExactStrategy` (internally subdivides large `simulateUntil` leaps into small substeps so analog thresholds are checked with bounded latency). The design intentionally avoids backend thread complexity by leveraging Xyce's synchronous `simulateUntil` API.

**Tech Stack:** Python 3.10+, `xyce_interface` (ctypes), `toffee_test`, existing `toffee.analog.xyce_simulator.XyceSimulator`.

---

### Task 1: Bootstrap the `mixed_signal` package skeleton

**Files:**
- Create: `toffee/mixed_signal/__init__.py`
- Create: `toffee/mixed_signal/port_mapping.py`
- Test: `tests/mixed_signal/test_port_mapping.py`

**Step 1: Write the failing test**

```python
# tests/mixed_signal/test_port_mapping.py
from toffee.mixed_signal.port_mapping import PortMapping, PortDirection

def test_port_mapping_basic():
    pm = PortMapping()
    pm.add_digital("dac_ctrl", direction=PortDirection.OUT)
    pm.add_analog("v_dac", direction=PortDirection.IN)
    pm.bridge("dac_ctrl", "v_dac", scale=1.8)
    assert pm.get_bridge("dac_ctrl") == ("v_dac", 1.8)
```

**Step 2: Run test to verify it fails**

```bash
cd /mnt/d/ongoingProjects/openEDA/toffee_project/toffee
pytest tests/mixed_signal/test_port_mapping.py -v
```

Expected: `ModuleNotFoundError: No module named 'toffee.mixed_signal'`

**Step 3: Create package skeleton**

```python
# toffee/mixed_signal/__init__.py
"""Mixed-signal verification utilities for toffee."""
```

```python
# toffee/mixed_signal/port_mapping.py
from enum import Enum, auto
from dataclasses import dataclass, field
from typing import Dict, Tuple, Optional


class PortDirection(Enum):
    IN = auto()
    OUT = auto()
    INOUT = auto()


@dataclass
class BridgeSpec:
    analog_name: str
    scale: float = 1.0
    offset: float = 0.0


class PortMapping:
    """Declarative map between digital DUT pins and analog SPICE nodes/params."""

    def __init__(self):
        self._digital: Dict[str, PortDirection] = {}
        self._analog: Dict[str, PortDirection] = {}
        self._bridges: Dict[str, BridgeSpec] = {}

    def add_digital(self, name: str, direction: PortDirection = PortDirection.INOUT):
        self._digital[name] = direction
        return self

    def add_analog(self, name: str, direction: PortDirection = PortDirection.INOUT):
        self._analog[name] = direction
        return self

    def bridge(self, digital_name: str, analog_name: str, scale: float = 1.0, offset: float = 0.0):
        if digital_name not in self._digital:
            raise KeyError(f"Digital port '{digital_name}' not declared")
        if analog_name not in self._analog:
            raise KeyError(f"Analog port '{analog_name}' not declared")
        self._bridges[digital_name] = BridgeSpec(analog_name, scale, offset)
        return self

    def get_bridge(self, digital_name: str) -> Tuple[str, float, float]:
        spec = self._bridges[digital_name]
        return spec.analog_name, spec.scale, spec.offset

    @property
    def digital_ports(self):
        return list(self._digital.keys())

    @property
    def analog_ports(self):
        return list(self._analog.keys())

    @property
    def bridges(self):
        return {k: (v.analog_name, v.scale, v.offset) for k, v in self._bridges.items()}
```

**Step 4: Run test to verify it passes**

```bash
pytest tests/mixed_signal/test_port_mapping.py -v
```

Expected: `test_port_mapping_basic PASSED`

**Step 5: Commit**

```bash
git add toffee/mixed_signal/__init__.py toffee/mixed_signal/port_mapping.py tests/mixed_signal/test_port_mapping.py
git commit -m "feat(mixed_signal): add PortMapping for digital↔analog bridge declarations"
```

---

### Task 2: MixedSignalSimulator core (wraps Xyce + digital DUT)

**Files:**
- Create: `toffee/mixed_signal/mixed_signal_simulator.py`
- Modify: `toffee/mixed_signal/__init__.py`
- Test: `tests/mixed_signal/test_mixed_signal_simulator.py`

**Step 1: Write the failing test**

```python
# tests/mixed_signal/test_mixed_signal_simulator.py
import pytest
import asyncio

from toffee.mixed_signal.mixed_signal_simulator import MixedSignalSimulator
from toffee.mixed_signal.port_mapping import PortMapping, PortDirection


class FakeDut:
    def __init__(self):
        self.dac_ctrl = 0


class FakeXyce:
    def __init__(self):
        self.time = 0.0
        self.dac_calls = []
        self.param_calls = []

    def simulateUntil(self, t):
        self.time = t
        return (1, t)

    def updateTimeVoltagePairs(self, name, times, voltages):
        self.dac_calls.append((name, times, voltages))

    def setCircuitParameter(self, name, value):
        self.param_calls.append((name, value))
        return 1

    def close(self):
        pass


def test_advance_applies_dac_bridge():
    dut = FakeDut()
    dut.dac_ctrl = 1
    xyce = FakeXyce()
    mapping = PortMapping()
    mapping.add_digital("dac_ctrl", PortDirection.OUT)
    mapping.add_analog("v_dac", PortDirection.IN)
    mapping.bridge("dac_ctrl", "v_dac", scale=1.8)

    sim = MixedSignalSimulator(xyce, dut, mapping)
    sim.advance_to(5e-9)

    assert xyce.time == 5e-9
    assert len(xyce.dac_calls) == 1
    name, times, voltages = xyce.dac_calls[0]
    assert name == "v_dac"
    assert voltages == [1.8]
```

**Step 2: Run test to verify it fails**

```bash
pytest tests/mixed_signal/test_mixed_signal_simulator.py::test_advance_applies_dac_bridge -v
```

Expected: `ImportError` or `AttributeError: module 'toffee.mixed_signal' has no attribute 'MixedSignalSimulator'`

**Step 3: Implement MixedSignalSimulator**

```python
# toffee/mixed_signal/mixed_signal_simulator.py
import asyncio
from typing import Any, Optional

from ..simulator import Simulator
from .port_mapping import PortMapping, PortDirection


class MixedSignalSimulator(Simulator):
    """Orchestrates a digital DUT and an analog Xyce backend.

    On every advance_to():
    1. Reads digital OUT ports from the DUT.
    2. Maps them to analog IN ports (DAC voltages or circuit parameters).
    3. Advances the analog simulator to the target time.
    """

    def __init__(self, analog_simulator, dut, port_mapping: PortMapping):
        self._analog = analog_simulator
        self._dut = dut
        self._mapping = port_mapping
        self._clock_event = asyncio.Event()
        self._current_time = 0.0

    def step_time(self, dt: float) -> None:
        requested = self._current_time + dt
        self.advance_to(requested)
        self.tick()

    def step(self, cycles: int = 1) -> None:
        self.step_time(1e-9 * cycles)

    def advance_to(self, time: float) -> None:
        if time > self._current_time:
            self._apply_digital_to_analog(time)
            status, actual = self._analog.simulateUntil(time)
            if status != 1:
                raise RuntimeError(
                    f"Analog simulator failed at {time} (status={status})"
                )
            self._current_time = actual

    def _apply_digital_to_analog(self, until_time: float):
        """Push digital pin values into analog world via bridges."""
        for d_name, spec in self._mapping._bridges.items():
            if self._mapping._digital.get(d_name) != PortDirection.OUT:
                continue
            raw_val = getattr(self._dut, d_name, None)
            if raw_val is None:
                continue
            analog_value = raw_val * spec.scale + spec.offset
            # Use updateTimeVoltagePairs for PWL DAC inputs
            if hasattr(self._analog, "updateTimeVoltagePairs"):
                self._analog.updateTimeVoltagePairs(
                    spec.analog_name,
                    [self._current_time, until_time],
                    [analog_value, analog_value],
                )

    @property
    def clock_event(self) -> asyncio.Event:
        return self._clock_event

    def get_signal_event(self, signal_name: str) -> asyncio.Event:
        return self._clock_event

    def read(self, variable_name: str) -> float:
        return self._analog.read(variable_name)

    def finish(self):
        if hasattr(self._analog, "finish"):
            self._analog.finish()
```

Update `__init__.py`:

```python
# toffee/mixed_signal/__init__.py
from .port_mapping import PortMapping, PortDirection
from .mixed_signal_simulator import MixedSignalSimulator
```

**Step 4: Run test to verify it passes**

```bash
pytest tests/mixed_signal/test_mixed_signal_simulator.py::test_advance_applies_dac_bridge -v
```

Expected: `PASSED`

**Step 5: Commit**

```bash
git add toffee/mixed_signal/__init__.py toffee/mixed_signal/mixed_signal_simulator.py tests/mixed_signal/test_mixed_signal_simulator.py
git commit -m "feat(mixed_signal): add MixedSignalSimulator with DAC bridging"
```

---

### Task 3: Add `setCircuitParameter` bridge support (resistor / load altering)

**Files:**
- Modify: `toffee/mixed_signal/port_mapping.py`
- Modify: `toffee/mixed_signal/mixed_signal_simulator.py`
- Test: `tests/mixed_signal/test_mixed_signal_simulator.py`

**Step 1: Write the failing test**

Append to `tests/mixed_signal/test_mixed_signal_simulator.py`:

```python
def test_advance_applies_param_bridge():
    class FakeDut2:
        r_load_ctrl = 2  # encoded as integer codes

    class FakeXyce2:
        def __init__(self):
            self.time = 0.0
            self.dac_calls = []
            self.param_calls = []

        def simulateUntil(self, t):
            self.time = t
            return (1, t)

        def updateTimeVoltagePairs(self, name, times, voltages):
            self.dac_calls.append((name, times, voltages))

        def setCircuitParameter(self, name, value):
            self.param_calls.append((name, value))
            return 1

        def close(self):
            pass

    dut = FakeDut2()
    xyce = FakeXyce2()
    mapping = PortMapping()
    mapping.add_digital("r_load_ctrl", PortDirection.OUT)
    mapping.add_analog("r_load", PortDirection.IN)
    # param bridge uses a mapping table: code -> resistance
    mapping.param_bridge("r_load_ctrl", "r_load", mapping={0: 1e3, 1: 10e3, 2: 100e3})

    sim = MixedSignalSimulator(xyce, dut, mapping)
    sim.advance_to(3e-9)

    assert xyce.time == 3e-9
    assert xyce.param_calls == [("r_load", 100e3)]
```

Run it; expect `AttributeError: 'PortMapping' object has no attribute 'param_bridge'`.

**Step 2: Extend PortMapping with param_bridge**

Add to `toffee/mixed_signal/port_mapping.py` inside `PortMapping`:

```python
@dataclass
class ParamBridgeSpec:
    param_name: str
    mapping: dict  # digital_code -> param_value


class PortMapping:
    # ... existing __init__ adds:
    #     self._param_bridges: Dict[str, ParamBridgeSpec] = {}

    def param_bridge(self, digital_name: str, param_name: str, mapping: dict):
        if digital_name not in self._digital:
            raise KeyError(f"Digital port '{digital_name}' not declared")
        self._param_bridges[digital_name] = ParamBridgeSpec(param_name, mapping)
        return self

    def get_param_bridge(self, digital_name: str) -> Tuple[str, dict]:
        spec = self._param_bridges[digital_name]
        return spec.param_name, spec.mapping
```

Update `__init__`:

```python
self._param_bridges: Dict[str, ParamBridgeSpec] = {}
```

**Step 3: Extend MixedSignalSimulator to handle param bridges**

In `_apply_digital_to_analog`, add after the voltage bridge loop:

```python
        for d_name, spec in self._mapping._param_bridges.items():
            raw_val = getattr(self._dut, d_name, None)
            if raw_val is None:
                continue
            if raw_val not in spec.mapping:
                raise ValueError(
                    f"Digital port '{d_name}' value {raw_val} not in param bridge mapping"
                )
            param_value = spec.mapping[raw_val]
            if hasattr(self._analog, "setCircuitParameter"):
                self._analog.setCircuitParameter(spec.param_name, param_value)
```

**Step 4: Run tests**

```bash
pytest tests/mixed_signal/test_mixed_signal_simulator.py -v
```

Expected: both tests pass.

**Step 5: Commit**

```bash
git add toffee/mixed_signal/port_mapping.py toffee/mixed_signal/mixed_signal_simulator.py tests/mixed_signal/test_mixed_signal_simulator.py
git commit -m "feat(mixed_signal): support setCircuitParameter bridging"
```

---

### Task 4: Step-Exact strategy for analog→digital precision

**Files:**
- Create: `toffee/mixed_signal/step_strategy.py`
- Modify: `toffee/mixed_signal/mixed_signal_simulator.py`
- Test: `tests/mixed_signal/test_step_exact.py`

**Step 1: Write the failing test**

```python
# tests/mixed_signal/test_step_exact.py
from toffee.mixed_signal.step_strategy import StepExactStrategy


def test_step_exact_subdivides():
    strategy = StepExactStrategy(max_step=2e-9)
    steps = list(strategy.iter_steps(current=0.0, target=7e-9))
    assert steps == [2e-9, 4e-9, 6e-9, 7e-9]


def test_step_exact_no_subdivision_when_under_max():
    strategy = StepExactStrategy(max_step=5e-9)
    steps = list(strategy.iter_steps(current=1e-9, target=3e-9))
    assert steps == [3e-9]
```

**Step 2: Run test to verify it fails**

```bash
pytest tests/mixed_signal/test_step_exact.py -v
```

Expected: `ModuleNotFoundError`

**Step 3: Implement StepExactStrategy**

```python
# toffee/mixed_signal/step_strategy.py
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
```

**Step 4: Integrate into MixedSignalSimulator**

Modify `MixedSignalSimulator.__init__` to accept optional `step_strategy`:

```python
    def __init__(self, analog_simulator, dut, port_mapping: PortMapping, step_strategy=None):
        ...
        self._step_strategy = step_strategy
```

Modify `advance_to` to use the strategy:

```python
    def advance_to(self, time: float) -> None:
        if time <= self._current_time:
            return
        self._apply_digital_to_analog(time)
        if self._step_strategy is not None:
            for sub_time in self._step_strategy.iter_steps(self._current_time, time):
                status, actual = self._analog.simulateUntil(sub_time)
                if status != 1:
                    raise RuntimeError(f"Analog simulator failed at {sub_time}")
                self._current_time = actual
        else:
            status, actual = self._analog.simulateUntil(time)
            if status != 1:
                raise RuntimeError(f"Analog simulator failed at {time}")
            self._current_time = actual
```

**Step 5: Run tests**

```bash
pytest tests/mixed_signal/test_step_exact.py tests/mixed_signal/test_mixed_signal_simulator.py -v
```

Expected: all pass.

**Step 6: Commit**

```bash
git add toffee/mixed_signal/step_strategy.py toffee/mixed_signal/mixed_signal_simulator.py tests/mixed_signal/test_step_exact.py
git commit -m "feat(mixed_signal): add StepExactStrategy for bounded analog threshold latency"
```

---

### Task 5: SAR ADC end-to-end test with Xyce

**Files:**
- Create: `tests/mixed_signal/test_sar_adc_xyce.py`
- Test data: inline netlist string (no new file needed)

**Step 1: Write the failing test**

```python
# tests/mixed_signal/test_sar_adc_xyce.py
import os
import tempfile

import toffee_test
from toffee import driver_method
from toffee.analog.xyce_simulator import XyceSimulator
from toffee.mixed_signal.mixed_signal_simulator import MixedSignalSimulator
from toffee.mixed_signal.port_mapping import PortMapping, PortDirection
from toffee.mixed_signal.step_strategy import StepExactStrategy


class FakeSarDut:
    """Fake digital SAR that outputs a 2-bit thermometer code to a DAC."""

    def __init__(self):
        self.dac_code = 0

    def set_code(self, code: int):
        self.dac_code = code


class SarEnv:
    def __init__(self):
        tb = os.path.join(tempfile.gettempdir(), "toffee_sar_adc.cir")
        with open(tb, "w") as f:
            f.write("* SAR ADC testbench\n")
            # Digital-driven DAC via PWL voltage
            f.write("B1 dac_in 0 V=table(time,0,0,1n,0)\n")
            f.write("R1 dac_in vout 1k\n")
            f.write("C1 vout 0 1p\n")
            f.write(".tran 0.01n 10n\n")
            f.write(".print tran V(vout)\n")
            f.write(".end\n")

        xyce = XyceSimulator(tb)
        self.dut = FakeSarDut()
        mapping = PortMapping()
        mapping.add_digital("dac_code", PortDirection.OUT)
        mapping.add_analog("dac_in", PortDirection.IN)
        # code 0 -> 0V, 1 -> 0.6V, 2 -> 1.2V, 3 -> 1.8V
        mapping.param_bridge(
            "dac_code", "B1", mapping={0: 0.0, 1: 0.6, 2: 1.2, 3: 1.8}
        )

        self.sim = MixedSignalSimulator(
            xyce, self.dut, mapping, step_strategy=StepExactStrategy(max_step=0.5e-9)
        )


@toffee_test.fixture
async def sar_env(toffee_request):
    env = toffee_request.create_env(SarEnv)
    yield env


@toffee_test.testcase
async def test_sar_adc_step_response(sar_env):
    sar_env.dut.set_code(3)
    sar_env.sim.advance_to(2e-9)
    vout = sar_env.sim.read("V(vout)")
    # At 2ns the RC should be close to 1.8V
    assert vout > 1.5, f"Expected vout > 1.5V at 2ns, got {vout}"
```

**Step 2: Run test to verify it fails**

```bash
pytest tests/mixed_signal/test_sar_adc_xyce.py -v
```

Expected: `AttributeError` because `XyceSimulator` doesn't expose `param_bridge` mapping directly; the test uses `setCircuitParameter` via `B1` which is a voltage source, and `setCircuitParameter` only works on `.param` names. The test may fail with a runtime error from Xyce.

**Step 3: Fix the test to use a real param**

Modify the netlist to use a parameter-driven voltage source:

```python
        with open(tb, "w") as f:
            f.write("* SAR ADC testbench\n")
            f.write(".param v_dac=0\n")
            f.write("V1 dac_in 0 DC {v_dac}\n")
            f.write("R1 dac_in vout 1k\n")
            f.write("C1 vout 0 1p\n")
            f.write(".tran 0.01n 10n\n")
            f.write(".print tran V(vout)\n")
            f.write(".end\n")
```

And update the mapping:

```python
        mapping.param_bridge(
            "dac_code", "v_dac", mapping={0: 0.0, 1: 0.6, 2: 1.2, 3: 1.8}
        )
```

**Step 4: Re-run the test**

```bash
pytest tests/mixed_signal/test_sar_adc_xyce.py -v
```

Expected: `PASSED` (assuming local Xyce install is functional).

**Step 5: Commit**

```bash
git add tests/mixed_signal/test_sar_adc_xyce.py
git commit -m "test(mixed_signal): add SAR ADC end-to-end test with Xyce"
```

---

### Task 6: (Optional Phase 3) ngspice async event backend

**Goal:** Add `_async_triggers` to `NgSpiceSimulator` so that `SendData` can detect threshold crossings and force `GetSyncData` to pause the background thread early.

**Files:**
- Modify: `toffee/analog/ngspice_simulator.py`
- Test: `tests/analog/test_ngspice_async_events.py`

**Step 1: Add `_async_triggers` API to NgSpiceSimulator**

In `toffee/analog/ngspice_simulator.py`, add to `__init__`:

```python
        self._async_triggers = {}  # node_name -> {"threshold": float, "armed": bool}
        self._trigger_lock = threading.Lock()
```

Add public methods:

```python
    def add_async_trigger(self, node_name: str, threshold: float):
        with self._trigger_lock:
            self._async_triggers[node_name] = {"threshold": threshold, "armed": True}

    def remove_async_trigger(self, node_name: str):
        with self._trigger_lock:
            self._async_triggers.pop(node_name, None)
```

**Step 2: Hook SendData to evaluate triggers**

In `_on_send_data`, after updating `self._node_voltages`, add:

```python
        with self._trigger_lock:
            for node, spec in self._async_triggers.items():
                if not spec["armed"]:
                    continue
                val = self._node_voltages.get(node)
                if val is not None and val >= spec["threshold"]:
                    spec["armed"] = False
                    # Force sync at the *next* GetSyncData call
                    self._next_sync_time = self._spice_time
```

**Step 3: Hook GetSyncData to respect trigger-induced sync times**

The existing `_on_get_sync_data_global` already checks `time_to_sync = self._next_sync_time - ckttime` and pauses when `<= 0`. No change needed there; setting `_next_sync_time = self._spice_time` ensures the next iteration sees `time_to_sync <= 0` and breaks out.

**Step 4: Write test**

```python
# tests/analog/test_ngspice_async_events.py
import pytest
from toffee.analog.ngspice_simulator import NgSpiceSimulator


def test_add_async_trigger_api():
    sim = NgSpiceSimulator()
    sim.add_async_trigger("V(out)", threshold=1.5)
    assert "V(out)" in sim._async_triggers
    sim.remove_async_trigger("V(out)")
    assert "V(out)" not in sim._async_triggers
```

Run it; commit.

**Step 5: Commit**

```bash
git add toffee/analog/ngspice_simulator.py tests/analog/test_ngspice_async_events.py
git commit -m "feat(ngspice): add async trigger support via SendData/GetSyncData"
```

---

## Post-Implementation Verification

Run the full mixed-signal test suite:

```bash
pytest tests/mixed_signal/ -v
```

Expected: all tests in Tasks 1–5 pass. Task 6 tests pass only if `libngspice0` is installed locally.
