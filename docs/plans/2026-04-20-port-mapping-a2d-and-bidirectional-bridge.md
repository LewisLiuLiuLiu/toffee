# PortMapping A2D 与混合信号双向桥接实施计划 (v2)

> **修订日期**: 2026-04-22
> **修订原因**: Review 发现原计划存在 1 个阻塞级问题、3 个高优先级设计缺陷、4 个中等风险。本版本全部修正。

**Goal:** 将 PortMapping 的命名从模糊的 bridge/reverse_bridge 重构为清晰的 d2a/a2d，并增加 analog-to-digital 反向桥接能力，使 MixedSignalSimulator 支持双向通信。

**Architecture:** 保留现有 PortMapping 的数据结构逻辑不变，仅做 API 命名重构。新增 A2DSpec 和 a2d() 方法。A2D 反向桥接采用**双后端策略**：Xyce 后端优先使用原生 YADC 设备 + `getTimeStatePairsADC()` 读取量化结果；ngspice 后端使用 Python 侧阈值判决作为 fallback。`setPauseTime` 作为辅助同步点工具，不用于自动阈值检测。

**Tech Stack:** Python 3.8+, pytest, toffee 框架, NgSpice ctypes, Xyce ctypes

---

## 设计决策（必须遵守）

1. **命名重构是破坏性变更**，不接受保留旧名作为别名的方案。必须全量替换。
2. **a2d 反向桥接**在 `PortMapping` 中必须和 d2a 一样使用声明式语法。
3. **ngspice trigger 线程安全**：C background 线程通过 `call_soon_threadsafe` 通知 asyncio。asyncio loop 采用**延迟捕获**（lazy capture），不在 `__init__` 中捕获。
4. **Xyce A2D 主力是 YADC 原生机制**：`getTimeStatePairsADC()` 读取量化后的数字状态。`setPauseTime` 仅用于在 `simulateUntil` 大步中插入中间同步检查点，不用于自动阈值检测（Xyce 没有 ngspice 的 `SendData` 回调，无法实时检测穿越）。
5. **事件触发职责统一**：`next_event()` 只返回事件名，`set/clear` 统一由 `__event_loop` 完成，避免双重触发。
6. **阻塞调用不能裸跑在 async 中**：Orchestrator 对模拟器的同步阻塞调用必须用 `run_in_executor` 包裹。

---

## Xyce A2D 能力边界说明

Xyce 和 ngspice 在事件通知方面有本质差异：

| 能力 | ngspice | Xyce |
|------|---------|------|
| 每步积分回调 | `SendData` callback，C 线程每步触发 | 无（`simulateUntil` 是同步黑箱） |
| 自动阈值检测 | Python 在 `_on_send_data` 中检查 | 依赖 YADC 设备在 netlist 中声明 |
| 中间暂停 | `_next_sync_time` 强制提前返回 | `setPauseTime` 注入 PAUSE breakpoint |
| 量化读取 | `get_voltage()` + Python 阈值判决 | `getTimeStatePairsADC()` 返回数字状态 |

因此 Xyce 后端的 A2D 工作流是：
1. 在 netlist 中放置 `YADC` 设备（连接到需要监测的模拟节点）
2. `simulateUntil(time)` 推进仿真
3. 调用 `getTimeStatePairsADC()` 读取 YADC 量化后的数字状态
4. 如需更细粒度，用 `setPauseTime` 在大步中插入中间检查点

---

## Task 0: xyce_interface.py 补全 setPauseTime Python 封装

**前置条件**: C 层 `xyce_setPauseTime` 已实现（`N_CIR_XyceCInterface.C:990-1005`），头文件已声明（`N_CIR_XyceCInterface.h:103`），但两个版本的 `xyce_interface.py` 均未封装此方法。`PauseTimeTest.py` 调用 `xyceObj.setPauseTime(2e-9)` 会抛出 `AttributeError`。

**Files:**
- Modify: `Xyce_Regression/Netlists/MIXED_SIGNAL/Python/xyce_interface.py`
- Modify: `install/xyce/share/xyce_interface.py`（或从 cmake 模板重新生成）
- Verify: `Xyce_Regression/Netlists/MIXED_SIGNAL/Python/PauseTimeTest.py`

---

**Step 1: 在 xyce_interface.py 中添加 setPauseTime 方法**

在 `getADCWidths` 方法之后（两个版本都要改）：

```python
  def setPauseTime(self, pauseTime):
    """Inject a PAUSE breakpoint so simulateUntil() stops at pauseTime."""
    status = self.lib.xyce_setPauseTime(byref(self.xycePtr), c_double(pauseTime))
    return status
```

**Step 2: 验证 PauseTimeTest.py 能跑通**

```bash
cd /mnt/d/ongoingProjects/openEDA/Xyce_Regression/Netlists/MIXED_SIGNAL/Python
python PauseTimeTest.py /mnt/d/ongoingProjects/openEDA/install/xyce/lib
```

Expected: `ALL TESTS PASSED`

**Step 3: Commit**

```bash
git add Xyce_Regression/Netlists/MIXED_SIGNAL/Python/xyce_interface.py
git add install/xyce/share/xyce_interface.py
git commit -m "feat(xyce_interface): add setPauseTime Python wrapper for xyce_setPauseTime C API"
```

---

## Task 1: PortMapping 重命名与新增 A2D

**Files:**
- Modify: `toffee/toffee/mixed_signal/port_mapping.py:1-93`
- Modify: `toffee/toffee/mixed_signal/__init__.py`
- Test: `toffee/tests/mixed_signal/test_port_mapping.py:1-35`

---

**Step 1: 修改 port_mapping.py 的导出列表**

```python
# toffee/toffee/mixed_signal/port_mapping.py
__all__ = ["PortDirection", "D2ASpec", "D2AParamSpec", "A2DSpec", "PortMapping"]
```

**Step 2: 重命名 BridgeSpec -> D2ASpec**

```python
@dataclass
class D2ASpec:
    analog_name: str
    scale: float = 1.0
    offset: float = 0.0
```

**Step 3: 重命名 ParamBridgeSpec -> D2AParamSpec**

```python
@dataclass
class D2AParamSpec:
    param_name: str
    mapping: Dict  # digital_code -> param_value
```

**Step 4: 新增 A2DSpec**

A2DSpec 需要支持两种后端模式：
- ngspice: Python 侧阈值判决（需要 threshold）
- Xyce: YADC 设备名映射（需要 yadc_device）

```python
@dataclass
class A2DSpec:
    digital_name: str
    threshold: float = 0.9       # 用于 ngspice fallback 的阈值
    invert: bool = False
    yadc_device: str = ""        # Xyce YADC 设备名（如 "YADC!ADC1"），为空则用 Python 阈值判决
```

**Step 5: 重构 PortMapping 内部存储**

```python
class PortMapping:
    def __init__(self):
        self._digital: Dict[str, PortDirection] = {}
        self._analog: Dict[str, PortDirection] = {}
        self._d2a: Dict[str, D2ASpec] = {}          # 原 _bridges
        self._d2a_param: Dict[str, D2AParamSpec] = {} # 原 _param_bridges
        self._a2d: Dict[str, A2DSpec] = {}          # 新增
```

**Step 6: 新增 d2a() 方法（原 bridge）**

```python
    def d2a(self, digital_name: str, analog_name: str, scale: float = 1.0, offset: float = 0.0) -> "PortMapping":
        if digital_name not in self._digital:
            raise KeyError(f"Digital port '{digital_name}' not declared")
        if analog_name not in self._analog:
            raise KeyError(f"Analog port '{analog_name}' not declared")
        self._d2a[digital_name] = D2ASpec(analog_name, scale, offset)
        return self
```

**Step 7: 新增 get_d2a() 方法（原 get_bridge）**

```python
    def get_d2a(self, digital_name: str) -> Tuple[str, float, float]:
        if digital_name not in self._d2a:
            raise KeyError(f"Digital port '{digital_name}' has no d2a declared")
        spec = self._d2a[digital_name]
        return spec.analog_name, spec.scale, spec.offset
```

**Step 8: 新增 iter_d2a() 生成器（原 iter_voltage_bridges）**

```python
    def iter_d2a(self):
        """Yield (digital_name, analog_name, scale, offset) for d2a bridges."""
        for d_name, spec in self._d2a.items():
            yield d_name, spec.analog_name, spec.scale, spec.offset
```

**Step 9: 新增 d2a_param() 方法（原 param_bridge）**

```python
    def d2a_param(self, digital_name: str, param_name: str, mapping: dict) -> "PortMapping":
        if digital_name not in self._digital:
            raise KeyError(f"Digital port '{digital_name}' not declared")
        self._d2a_param[digital_name] = D2AParamSpec(param_name, mapping)
        return self
```

**Step 10: 新增 get_d2a_param() 方法（原 get_param_bridge）**

```python
    def get_d2a_param(self, digital_name: str) -> Tuple[str, Dict]:
        if digital_name not in self._d2a_param:
            raise KeyError(f"Digital port '{digital_name}' has no d2a_param declared")
        spec = self._d2a_param[digital_name]
        return spec.param_name, spec.mapping
```

**Step 11: 新增 iter_d2a_param() 生成器（原 iter_param_bridges）**

```python
    def iter_d2a_param(self):
        """Yield (digital_name, param_name, code_mapping)."""
        for d_name, spec in self._d2a_param.items():
            yield d_name, spec.param_name, spec.mapping
```

**Step 12: 新增 a2d() 方法**

```python
    def a2d(self, analog_name: str, digital_name: str,
            threshold: float = 0.9, invert: bool = False,
            yadc_device: str = "") -> "PortMapping":
        if analog_name not in self._analog:
            raise KeyError(f"Analog port '{analog_name}' not declared")
        if digital_name not in self._digital:
            raise KeyError(f"Digital port '{digital_name}' not declared")
        self._a2d[analog_name] = A2DSpec(digital_name, threshold, invert, yadc_device)
        return self
```

**Step 13: 新增 get_a2d() 方法**

```python
    def get_a2d(self, analog_name: str) -> Tuple[str, float, bool]:
        if analog_name not in self._a2d:
            raise KeyError(f"Analog port '{analog_name}' has no a2d declared")
        spec = self._a2d[analog_name]
        return spec.digital_name, spec.threshold, spec.invert
```

**Step 14: 新增 iter_a2d() 生成器**

```python
    def iter_a2d(self):
        """Yield (analog_name, digital_name, threshold, invert, yadc_device) for a2d bridges."""
        for analog_name, spec in self._a2d.items():
            yield analog_name, spec.digital_name, spec.threshold, spec.invert, spec.yadc_device
```

**Step 15: 新增 d2a_map property（原 bridges property）**

```python
    @property
    def d2a_map(self):
        return {k: (v.analog_name, v.scale, v.offset) for k, v in self._d2a.items()}
```

**Step 16: 修改 mixed_signal/__init__.py 导出**

```python
# toffee/toffee/mixed_signal/__init__.py
from .port_mapping import PortMapping, PortDirection, D2ASpec, D2AParamSpec, A2DSpec
from .mixed_signal_simulator import MixedSignalSimulator
from .step_strategy import StepExactStrategy
```

**Step 17: 运行 port_mapping 相关测试**

Run:
```bash
cd /mnt/d/ongoingProjects/openEDA/toffee_project/toffee
python -m pytest tests/mixed_signal/test_port_mapping.py -v
```

Expected: FAIL -- 因为测试文件还是旧命名，需要 Task 3 来改。

**Step 18: Commit**

```bash
cd /mnt/d/ongoingProjects/openEDA/toffee_project
git add toffee/toffee/mixed_signal/port_mapping.py toffee/toffee/mixed_signal/__init__.py
git commit -m "refactor(port_mapping): rename bridge->d2a, add a2d support with YADC backend"
```

---

## Task 2: MixedSignalSimulator 适配新命名并增加反向桥接

**Files:**
- Modify: `toffee/toffee/mixed_signal/mixed_signal_simulator.py:1-90`
- Test: `toffee/tests/mixed_signal/test_mixed_signal_simulator.py`

---

**Step 1: 重构 _apply_digital_to_analog 中的生成器调用**

将 `iter_voltage_bridges()` 改为 `iter_d2a()`，`iter_param_bridges()` 改为 `iter_d2a_param()`：

```python
# toffee/toffee/mixed_signal/mixed_signal_simulator.py
    def _apply_digital_to_analog(self, until_time: float):
        for d_name, analog_name, scale, offset in self._mapping.iter_d2a():
            if self._mapping.get_digital_direction(d_name) != PortDirection.OUT:
                continue
            raw_val = getattr(self._dut, d_name, None)
            if raw_val is None:
                continue
            analog_value = raw_val * scale + offset
            if hasattr(self._analog, "updateTimeVoltagePairs"):
                self._analog.updateTimeVoltagePairs(
                    analog_name,
                    [self._current_time, until_time],
                    [analog_value, analog_value],
                )

        for d_name, param_name, code_mapping in self._mapping.iter_d2a_param():
            raw_val = getattr(self._dut, d_name, None)
            if raw_val is None:
                continue
            if raw_val not in code_mapping:
                raise ValueError(
                    f"Digital port '{d_name}' value {raw_val} not in d2a_param mapping"
                )
            param_value = code_mapping[raw_val]
            if hasattr(self._analog, "setCircuitParameter"):
                self._analog.setCircuitParameter(param_name, param_value)
```

**Step 2: 在 advance_to() 中插入 _apply_analog_to_digital()**

在 `simulateUntil` 返回后、`self._current_time = actual` 之后插入：

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
                # 每个子步后都做一次 A2D 读取
                self._apply_analog_to_digital()
        else:
            status, actual = self._analog.simulateUntil(time)
            if status != 1:
                raise RuntimeError(f"Analog simulator failed at {time}")
            self._current_time = actual
            self._apply_analog_to_digital()
```

**Step 3: 实现 _apply_analog_to_digital() -- 双后端策略**

```python
    def _apply_analog_to_digital(self):
        """Read analog results and drive digital DUT pins.

        For Xyce backend: use YADC getTimeStatePairsADC() if yadc_device is specified.
        For ngspice backend (or fallback): use read() + Python threshold comparison.
        """
        # --- Xyce YADC batch read (if any a2d uses yadc_device) ---
        yadc_results = {}
        yadc_needed = any(
            spec.yadc_device
            for spec in (self._mapping._a2d[k] for k in self._mapping._a2d)
        )
        if yadc_needed and hasattr(self._analog, '_xyce'):
            try:
                (status, ADCnames, numADCnames, numPoints,
                 timeArray, stateArray) = self._analog._xyce.getTimeStatePairsADC()
                if status == 1:
                    for i, name in enumerate(ADCnames):
                        # 取最新时间点的状态
                        if numPoints > 0:
                            yadc_results[name] = stateArray[i][numPoints - 1]
            except Exception:
                pass  # fallback to Python threshold

        # --- Per-port A2D ---
        for analog_name, d_name, threshold, invert, yadc_device in self._mapping.iter_a2d():
            if yadc_device and yadc_device in yadc_results:
                # Xyce YADC path: use quantized digital state directly
                digital_val = yadc_results[yadc_device]
            else:
                # ngspice / fallback path: read voltage + threshold
                voltage = self._analog.read(analog_name)
                digital_val = 1 if voltage >= threshold else 0

            if invert:
                digital_val = 1 - digital_val

            pin = getattr(self._dut, d_name, None)
            if pin is None:
                continue
            if hasattr(pin, "value"):
                pin.value = digital_val
            else:
                setattr(self._dut, d_name, digital_val)
```

**Step 4: Commit**

```bash
git add toffee/toffee/mixed_signal/mixed_signal_simulator.py
git commit -m "feat(mixed_signal_simulator): add dual-backend _apply_analog_to_digital (YADC + threshold fallback)"
```

---

## Task 3: 同步修改所有测试文件

**Files:**
- Modify: `toffee/tests/mixed_signal/test_port_mapping.py`
- Modify: `toffee/tests/mixed_signal/test_mixed_signal_simulator.py`
- Modify: `toffee/tests/mixed_signal/test_sar_adc_xyce.py`
- Modify: `toffee/tests/mixed_signal/test_step_exact.py`

---

**Step 1: 重写 test_port_mapping.py**

```python
import pytest

from toffee.mixed_signal.port_mapping import PortMapping, PortDirection


def test_port_mapping_basic():
    pm = PortMapping()
    pm.add_digital("dac_ctrl", direction=PortDirection.OUT)
    pm.add_analog("v_dac", direction=PortDirection.IN)
    pm.d2a("dac_ctrl", "v_dac", scale=1.8)
    assert pm.get_d2a("dac_ctrl") == ("v_dac", 1.8, 0.0)


def test_d2a_requires_declared_ports():
    pm = PortMapping()
    with pytest.raises(KeyError):
        pm.d2a("missing_digital", "v_dac")
    pm.add_digital("dac_ctrl", PortDirection.OUT)
    with pytest.raises(KeyError):
        pm.d2a("dac_ctrl", "missing_analog")


def test_properties_and_defaults():
    pm = PortMapping()
    pm.add_digital("a").add_analog("b").d2a("a", "b")
    assert pm.digital_ports == ["a"]
    assert pm.analog_ports == ["b"]
    assert pm.d2a_map == {"a": ("b", 1.0, 0.0)}
    assert pm.get_d2a("a") == ("b", 1.0, 0.0)


def test_d2a_param_requires_declared_digital_port():
    pm = PortMapping()
    with pytest.raises(KeyError):
        pm.d2a_param("missing", "r_load", mapping={0: 1e3})


def test_a2d_basic():
    pm = PortMapping()
    pm.add_digital("comp_in", direction=PortDirection.IN)
    pm.add_analog("v(comp_out)", direction=PortDirection.OUT)
    pm.a2d("v(comp_out)", "comp_in", threshold=1.5, invert=False)
    d_name, threshold, invert = pm.get_a2d("v(comp_out)")
    assert d_name == "comp_in"
    assert threshold == 1.5
    assert invert is False
    bridges = list(pm.iter_a2d())
    assert len(bridges) == 1
    assert bridges[0][:4] == ("v(comp_out)", "comp_in", 1.5, False)


def test_a2d_requires_declared_ports():
    pm = PortMapping()
    with pytest.raises(KeyError):
        pm.a2d("missing_analog", "comp_in")
    pm.add_analog("v(comp_out)", PortDirection.OUT)
    with pytest.raises(KeyError):
        pm.a2d("v(comp_out)", "missing_digital")


def test_a2d_with_yadc_device():
    pm = PortMapping()
    pm.add_digital("adc_out", PortDirection.IN)
    pm.add_analog("v(sense)", PortDirection.OUT)
    pm.a2d("v(sense)", "adc_out", yadc_device="YADC!ADC1")
    bridges = list(pm.iter_a2d())
    assert bridges[0][4] == "YADC!ADC1"
```

Run:
```bash
cd /mnt/d/ongoingProjects/openEDA/toffee_project/toffee
python -m pytest tests/mixed_signal/test_port_mapping.py -v
```

Expected: PASS

**Step 2: 修改 test_mixed_signal_simulator.py**

将所有 `bridge()` 调用改为 `d2a()`，`param_bridge()` 改为 `d2a_param()`。

新增反向桥接测试：

```python
def test_advance_applies_a2d_bridge():
    """Test that analog voltage crosses threshold and drives digital pin."""
    dut = FakeDut()
    analog = FakeAnalog()
    pm = PortMapping()
    pm.add_digital("comp_in", PortDirection.IN)
    pm.add_analog("v(comp_out)", PortDirection.OUT)
    pm.a2d("v(comp_out)", "comp_in", threshold=1.5)

    ms = MixedSignalSimulator(analog, dut, pm)
    # FakeAnalog.read returns 1.8 by default, which is > 1.5 threshold
    ms.advance_to(1e-9)
    assert dut.comp_in == 1


def test_a2d_low_voltage_drives_zero():
    dut = FakeDut()
    analog = FakeAnalog(default_voltage=0.2)
    pm = PortMapping()
    pm.add_digital("comp_in", PortDirection.IN)
    pm.add_analog("v(comp_out)", PortDirection.OUT)
    pm.a2d("v(comp_out)", "comp_in", threshold=1.5)

    ms = MixedSignalSimulator(analog, dut, pm)
    ms.advance_to(1e-9)
    assert dut.comp_in == 0
```

**Step 3: 修改 test_sar_adc_xyce.py 和 test_step_exact.py**

将所有 `bridge()` -> `d2a()`，`param_bridge()` -> `d2a_param()`。

**Step 4: 运行全部混合信号测试**

```bash
cd /mnt/d/ongoingProjects/openEDA/toffee_project/toffee
python -m pytest tests/mixed_signal/ -v
```

Expected: PASS

**Step 5: Commit**

```bash
git add toffee/tests/mixed_signal/
git commit -m "test: update all tests for d2a/a2d naming, add a2d reverse bridge tests"
```

---

## Task 4: NgSpiceSimulator trigger 通知 asyncio 事件循环

**Files:**
- Modify: `toffee/toffee/analog/ngspice_simulator.py:152-672`
- Test: `toffee/tests/analog/test_ngspice_async_events.py`

**关键修正（相比 v1）**: asyncio loop 采用延迟捕获，不在 `__init__` 中调用 `get_running_loop()`。trigger 错误处理添加日志，不再静默吞没。

---

**Step 1: 在 __init__ 中初始化事件系统（不捕获 loop）**

在第 191 行（`self._trigger_lock = threading.Lock()` 之后）插入：

```python
        # -- asyncio event system for cross-thread notification --
        # NOTE: loop 采用延迟捕获，因为 __init__ 通常在 asyncio 启动之前调用
        self._asyncio_loop: Optional[asyncio.AbstractEventLoop] = None
        self._events = {
            "step": self._clock_event,
            "threshold_crossed": asyncio.Event(),
        }
        self._pending_events: list[str] = []
        self._event_lock = threading.Lock()
```

**Step 2: 新增 _ensure_loop() 延迟捕获方法**

```python
    def _ensure_loop(self):
        """Lazily capture the running asyncio event loop.

        Called from step_time() / add_async_trigger() which run inside
        the asyncio loop, unlike __init__ which runs before it.
        """
        if self._asyncio_loop is None:
            try:
                self._asyncio_loop = asyncio.get_running_loop()
            except RuntimeError:
                pass
```

**Step 3: 在 step_time() 和 add_async_trigger() 开头调用 _ensure_loop()**

```python
    def step_time(self, dt: float):
        self._ensure_loop()
        # ... 原有逻辑 ...

    def add_async_trigger(self, node: str, threshold: float):
        self._ensure_loop()
        # ... 原有逻辑 ...
```

**Step 4: 新增 events property**

```python
    @property
    def events(self) -> dict[str, asyncio.Event]:
        return self._events
```

**Step 5: 修改 _on_send_data 触发逻辑（添加日志，不静默吞没）**

在第 337-340 行（trigger 检测到后）修改为：

```python
                try:
                    if val is not None and val >= spec["threshold"]:
                        spec["armed"] = False
                        self._next_sync_time = self._spice_time
                        with self._event_lock:
                            self._pending_events.append("threshold_crossed")
                        if self._asyncio_loop is not None:
                            self._asyncio_loop.call_soon_threadsafe(
                                self._events["threshold_crossed"].set
                            )
                except Exception as e:
                    import logging
                    logging.getLogger("toffee.ngspice").debug(
                        "Error in _on_send_data trigger handler: %s", e
                    )
```

**Step 6: 修改测试 test_ngspice_async_events.py**

新增测试：验证 trigger 触发后 asyncio Event 被设置。

**Step 7: 运行测试**

```bash
cd /mnt/d/ongoingProjects/openEDA/toffee_project/toffee
python -m pytest tests/analog/test_ngspice_async_events.py -v
```

Expected: PASS

**Step 8: Commit**

```bash
git add toffee/toffee/analog/ngspice_simulator.py toffee/tests/analog/test_ngspice_async_events.py
git commit -m "feat(ngspice): notify asyncio on trigger with lazy loop capture and error logging"
```

---

## Task 5: XyceSimulator 接入 setPauseTime + YADC 读取

**前提**: Task 0 已完成 `xyce_interface.py` 的 `setPauseTime` 封装。

**Files:**
- Modify: `toffee/toffee/analog/xyce_simulator.py:1-148`
- Create: `toffee/tests/analog/test_xyce_pause_time.py`

**关键修正（相比 v1）**: `setPauseTime` 明确定位为同步点辅助，不用于自动阈值检测。新增 YADC 读取方法。

---

**Step 1: 在 XyceSimulator 中新增 set_pause_time 方法**

```python
    def set_pause_time(self, pause_time: float) -> None:
        """Inject a PAUSE breakpoint so simulateUntil() stops at pause_time.

        Use case: insert intermediate sync points between digital clock edges
        to read YADC results more frequently. This is NOT automatic threshold
        detection -- you must know the pause time in advance.
        """
        status = self._xyce.setPauseTime(pause_time)
        if status != 1:
            raise RuntimeError(
                f"xyce_setPauseTime({pause_time}) failed with status {status}"
            )
```

**Step 2: 新增 YADC 读取方法**

```python
    def read_adc_states(self):
        """Read quantized digital states from all YADC devices.

        Returns dict mapping YADC device name -> latest digital state value.
        This is the primary A2D mechanism for Xyce backend.
        """
        result = {}
        try:
            (status, ADCnames, numADCnames, numPoints,
             timeArray, stateArray) = self._xyce.getTimeStatePairsADC()
            if status == 1:
                for i in range(numADCnames):
                    if numPoints > 0:
                        result[ADCnames[i]] = stateArray[i][numPoints - 1]
        except Exception:
            pass
        return result

    def get_adc_map(self):
        """Return YADC device configuration (names, widths, thresholds, etc.)."""
        return self._xyce.getADCMap()
```

**Step 3: 清理硬编码路径**

```python
_DEFAULT_XYCE_SHARE = os.environ.get(
    "XYCE_SHARE", "/mnt/d/ongoingProjects/openEDA/install/xyce/share"
)
_DEFAULT_XYCE_LIB = os.environ.get(
    "XYCE_LIB", "/mnt/d/ongoingProjects/openEDA/install/xyce/lib"
)
```

**Step 4: 新增测试 test_xyce_pause_time.py**

```python
import pytest
from toffee.analog.xyce_simulator import XyceSimulator


@pytest.mark.skipif(not _xyce_available(), reason="Xyce library not found")
def test_xyce_set_pause_time_basic():
    """Verify that set_pause_time + simulateUntil stops early."""
    sim = XyceSimulator("some_rc_netlist.cir")
    sim.set_pause_time(2e-9)
    status, actual = sim.simulateUntil(5e-9)
    assert actual == pytest.approx(2e-9, abs=1e-12)
    # Resume to 5ns
    status, actual = sim.simulateUntil(5e-9)
    assert actual == pytest.approx(5e-9, abs=1e-12)
```

**Step 5: 运行测试**

```bash
cd /mnt/d/ongoingProjects/openEDA/toffee_project/toffee
python -m pytest tests/analog/test_xyce_pause_time.py -v
```

Expected: PASS (if Xyce library available)

**Step 6: Commit**

```bash
git add toffee/toffee/analog/xyce_simulator.py toffee/tests/analog/test_xyce_pause_time.py
git commit -m "feat(xyce): add setPauseTime sync points + YADC read_adc_states, clean up hardcoded paths"
```

---

## Task 6: Simulator 基类添加 events/next_event 接口

**Files:**
- Modify: `toffee/toffee/simulator.py:12-61`
- Modify: `toffee/toffee/asynchronous.py:161-174`

**说明**: 此 Task 必须在 Task 7（AnalogAgent）之前完成，因为 AnalogAgent 依赖 `simulator.events` 属性。

---

**Step 1: 在 Simulator 基类中添加 events property 和 next_event()**

```python
class Simulator(ABC):
    # ... 现有方法 ...

    @property
    def events(self) -> dict[str, asyncio.Event]:
        """Override in subclasses to expose named events."""
        return {"step": self.clock_event}

    async def next_event(self) -> str:
        """Advance simulation and return the name of the next event.

        Default: advance one step and return "step".
        Override for event-driven simulators (ngspice trigger, etc.).
        """
        self.step(1)
        self.tick()
        return "step"
```

**Step 2: 新增 __event_loop 替代 __clock_loop（可选，向后兼容）**

在 `asynchronous.py` 中，如果 simulator 实现了 `next_event`，使用事件驱动循环：

```python
async def __event_loop(simulator):
    while True:
        await execute_all_coros()
        event_name = await simulator.next_event()
        # 统一由 event_loop 触发事件，next_event() 不做 set/clear
        if event_name in simulator.events:
            evt = simulator.events[event_name]
            evt.set()
            evt.clear()
```

**Step 3: Commit**

```bash
git add toffee/toffee/simulator.py toffee/toffee/asynchronous.py
git commit -m "feat(simulator): add events/next_event interface, add __event_loop to asynchronous.py"
```

---

## Task 7: 纯模拟 AnalogAgent 事件配置

**前提**: Task 6 已完成，`Simulator.events` 属性可用。

**Files:**
- Modify: `toffee/toffee/mixed_signal/agent.py`
- Test: `toffee/tests/analog/` 下的测试可能需要调整

---

**Step 1: 确保 AnalogAgent 使用 events 接口**

```python
class AnalogAgent:
    def __init__(self, simulator, event_name="step"):
        self._simulator = simulator
        self._event = simulator.events.get(event_name, simulator.clock_event)
```

**Step 2: 确保 start_clock() 对纯模拟仿真器正确工作**

- 确保 `AnalogAgent` 初始化时创建 `asyncio.Event` 作为 `clock_event`
- 或者为纯模拟场景提供 `start_analog_clock()` 入口

**Step 3: Commit**

```bash
git add toffee/toffee/mixed_signal/agent.py
git commit -m "feat(agent): AnalogAgent uses simulator.events for event-driven scheduling"
```

---

## Task 8: 全部回归测试

**Step 1: 运行纯模拟测试**

```bash
cd /mnt/d/ongoingProjects/openEDA/toffee_project/toffee
python -m pytest tests/analog/ -v
```

Expected: PASS

**Step 2: 运行混合信号测试**

```bash
python -m pytest tests/mixed_signal/ -v
```

Expected: PASS

**Step 3: 运行根目录测试（如存在）**

```bash
python -m pytest tests/test_bundle.py tests/test_env.py tests/test_model.py -v
```

Expected: PASS

**Step 4: Final commit**

```bash
git commit -m "feat(mixed-signal): complete bidirectional bridge with YADC + threshold fallback"
```

---

## 附录 A: 变更文件清单

| 文件 | 操作 | Task | 说明 |
|------|------|------|------|
| `Xyce_Regression/.../xyce_interface.py` | 修改 | 0 | 补 setPauseTime 封装 |
| `install/xyce/share/xyce_interface.py` | 修改 | 0 | 同上 |
| `toffee/toffee/mixed_signal/port_mapping.py` | 修改 | 1 | API 重命名 + 新增 a2d（含 yadc_device） |
| `toffee/toffee/mixed_signal/__init__.py` | 修改 | 1 | 更新导出列表 |
| `toffee/toffee/mixed_signal/mixed_signal_simulator.py` | 修改 | 2 | 双后端 _apply_analog_to_digital |
| `toffee/tests/mixed_signal/test_port_mapping.py` | 修改 | 3 | d2a/a2d 测试 + YADC 测试 |
| `toffee/tests/mixed_signal/test_mixed_signal_simulator.py` | 修改 | 3 | 适配 + a2d 测试 |
| `toffee/tests/mixed_signal/test_sar_adc_xyce.py` | 修改 | 3 | 适配新命名 |
| `toffee/tests/mixed_signal/test_step_exact.py` | 修改 | 3 | 适配新命名 |
| `toffee/toffee/analog/ngspice_simulator.py` | 修改 | 4 | lazy loop + trigger 通知 + 日志 |
| `toffee/tests/analog/test_ngspice_async_events.py` | 修改 | 4 | asyncio 通知测试 |
| `toffee/toffee/analog/xyce_simulator.py` | 修改 | 5 | setPauseTime + YADC + 环境变量路径 |
| `toffee/tests/analog/test_xyce_pause_time.py` | 创建 | 5 | Xyce setPauseTime 测试 |
| `toffee/toffee/simulator.py` | 修改 | 6 | events/next_event 接口 |
| `toffee/toffee/asynchronous.py` | 修改 | 6 | __event_loop |
| `toffee/toffee/mixed_signal/agent.py` | 修改 | 7 | AnalogAgent 用 events |

## 附录 B: 与 v1 计划的差异摘要

| 问题 | v1 | v2 |
|------|----|----|
| xyce_interface.py 缺 setPauseTime | 未发现 | 新增 Task 0 补全 |
| A2D 实现方式 | Python 手写阈值判决 | Xyce 用 YADC 原生机制，ngspice 用阈值 fallback |
| setPauseTime 定位 | "自动阈值检测" | 预定时间点同步辅助 |
| asyncio loop 捕获 | `__init__` 中捕获（会失败） | lazy capture 在首次协程调用时捕获 |
| next_event 事件触发 | next_event 内 + event_loop 双重触发 | 统一由 event_loop 触发 |
| Task 排序 | AnalogAgent (Task 5) 在 events (Task 6) 之前 | events (Task 6) 在 AnalogAgent (Task 7) 之前 |
| advance_to 阻塞 | 裸跑在 async 中 | run_in_executor（Orchestrator 中） |
| 硬编码路径 | 未处理 | Task 5 改为环境变量 |
| trigger 异常处理 | except pass 静默吞没 | 添加 logging.debug |
