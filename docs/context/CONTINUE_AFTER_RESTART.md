# toffee 混合信号扩展 -- 完整上下文（供新 Agent 继续）

> **状态**: 测试风格统一已完成（已提交）。计划已升级到 v2（2026-04-22 修订）。Task 0~8 均尚未开始写代码。
> **计划文档**: `docs/plans/2026-04-20-port-mapping-a2d-and-bidirectional-bridge.md` (v2)
> **目标**: 实现数字<->模拟双向桥接（PortMapping 支持 `a2d` 反向桥接）。

---

## 一、项目架构

```
/mnt/d/ongoingProjects/openEDA/toffee_project/
├── toffee/                     # 核心框架（git 仓库，当前工作目录）
│   ├── toffee/                 # Python 包源码
│   │   ├── simulator.py        # Simulator ABC（step/step_time/clock_event）
│   │   ├── asynchronous.py     # 异步事件循环（__clock_loop / start_clock）
│   │   ├── mixed_signal/
│   │   │   ├── port_mapping.py           # PortMapping 类（当前单向）
│   │   │   ├── mixed_signal_simulator.py # 协调数字+模拟仿真器
│   │   │   ├── step_exact_strategy.py    # 步长策略
│   │   │   └── agent.py                  # AnalogAgent
│   │   ├── analog/
│   │   │   ├── ngspice_simulator.py      # ctypes + lazy sync + async trigger
│   │   │   ├── xyce_simulator.py         # Xyce 封装（缺 setPauseTime + YADC）
│   │   │   └── ...
│   │   └── ...
│   ├── tests/
│   │   ├── analog/             # ngspice/Xyce 纯模拟测试
│   │   └── mixed_signal/       # 混合信号测试
│   └── docs/plans/             # 实施计划
├── toffee-test/                # pytest 插件（@toffee_test.testcase）
│   └── toffee_test/
├── Xyce/                       # Xyce 源码（含用户改造的 C API）
│   └── utils/XyceCInterface/
│       ├── N_CIR_XyceCInterface.h   # xyce_setPauseTime 已声明
│       └── N_CIR_XyceCInterface.C   # xyce_setPauseTime 已实现 (line 990-1005)
├── Xyce_Regression/            # Xyce 回归测试
│   └── Netlists/MIXED_SIGNAL/Python/
│       ├── xyce_interface.py          # Python ctypes wrapper (缺 setPauseTime)
│       └── PauseTimeTest.py           # setPauseTime 测试 (当前跑不通)
├── install/xyce/share/
│   └── xyce_interface.py              # 安装版 wrapper (也缺 setPauseTime)
└── toffee_ana/                 # SPICE 参考设计
```

**Python 3.10.12，pytest 9.0.2。**
所有混合信号测试放在 `toffee/tests/` 下（不是 `toffee-test/`）。

---

## 二、已完成的工作（git log）

最近的 8 个 commit 都在 master 上，ahead of origin/master：

```
fa5f987  style(tests): unify analog/mixed-signal tests with @toffee_test.testcase  <- 最新
1434c05  feat(ngspice): add async trigger support via SendData/GetSyncData
0332b48  feat(analog,mixed_signal): add Xyce compatibility aliases and SAR ADC end-to-end test
222b367  feat(mixed_signal): add StepExactStrategy for bounded analog threshold latency
f86529b  feat(mixed_signal): support setCircuitParameter bridging
... (还有更早的 3 个 commit)
```

### 2.1 已完成的文件变更

- **ngspice_simulator.py**: 支持 bg_run、lazy sync、async trigger（`add_async_trigger`）
- **xyce_simulator.py**: 添加了 `updateTimeVoltagePairs` 和 `setCircuitParameter` 别名（供 MixedSignalSimulator 调用）
- **test_sar_adc_xyce.py**: 端到端 SAR ADC 测试（StepExactStrategy）
- **step_exact_strategy.py**: 步长策略
- **6 个测试文件**: 统一为 `@toffee_test.testcase` + `async def` 风格

---

## 三、v2 计划概要（9 个 Task）

### 设计决策（必须遵守）

1. **命名重构是破坏性变更**，不接受保留旧名作为别名的方案。必须全量替换。
2. **a2d 反向桥接**在 `PortMapping` 中必须和 d2a 一样使用声明式语法。
3. **ngspice trigger 线程安全**: C background 线程通过 `call_soon_threadsafe` 通知 asyncio。**asyncio loop 延迟捕获**，不在 `__init__` 中。
4. **Xyce A2D 主力是 YADC 原生机制**: `getTimeStatePairsADC()` 读取量化数字状态。`setPauseTime` 仅用于同步点辅助。
5. **事件触发职责统一**: `next_event()` 只返回事件名，`set/clear` 由 `__event_loop` 完成。
6. **阻塞调用不能裸跑在 async 中**: 用 `run_in_executor` 包裹。

### v2 与 v1 的关键差异

| 问题 | v1 | v2 |
|------|----|----|
| xyce_interface.py 缺 setPauseTime | 未发现 | 新增 Task 0 补全 |
| A2D 实现方式 | Python 手写阈值判决 | Xyce 用 YADC 原生机制，ngspice 用阈值 fallback |
| setPauseTime 定位 | "自动阈值检测" | 预定时间点同步辅助 |
| asyncio loop 捕获 | __init__ 中（会失败） | lazy capture |
| next_event 事件触发 | 双重触发 | 统一由 event_loop 触发 |
| Task 排序 | AnalogAgent 在 events 之前 | events 在 AnalogAgent 之前 |

### Task 列表

| Task | 内容 | 涉及文件 |
|------|------|----------|
| 0 | xyce_interface.py 补 setPauseTime 封装 | xyce_interface.py (两个版本) |
| 1 | PortMapping 重命名 bridge->d2a + 新增 a2d (含 yadc_device) | port_mapping.py, __init__.py |
| 2 | MixedSignalSimulator 双后端 _apply_analog_to_digital | mixed_signal_simulator.py |
| 3 | 同步修改所有测试文件 | test_port_mapping.py, test_mixed_signal_simulator.py, ... |
| 4 | NgSpice trigger 通知 asyncio (lazy loop + logging) | ngspice_simulator.py, test_ngspice_async_events.py |
| 5 | Xyce setPauseTime + YADC read_adc_states + 清理路径 | xyce_simulator.py, test_xyce_pause_time.py |
| 6 | Simulator 基类 events/next_event + __event_loop | simulator.py, asynchronous.py |
| 7 | AnalogAgent 事件配置 (依赖 Task 6) | agent.py |
| 8 | 全部回归测试 | - |

---

## 四、关键代码文件摘要（当前状态）

### 4.1 `toffee/toffee/simulator.py`（61 行）

```python
class Simulator(ABC):
    @abstractmethod
    def step(self, cycles: int): ...
    def step_time(self, dt: float): raise NotImplementedError
    @property
    def clock_event(self) -> asyncio.Event: ...
    def tick(self): ...
    @abstractmethod
    def get_signal_event(self, signal_name: str) -> asyncio.Event: ...
```

当前没有 `events` 字典和 `next_event()`。Task 6 将添加。

### 4.2 `toffee/toffee/asynchronous.py`（357 行）

`__clock_loop(simulator)` (line 161-173): step(1) + tick() 循环。
`__has_unwait_task()` (line 55-68): 硬编码跳过 `"__clock_loop"` 名称。

### 4.3 `toffee/toffee/mixed_signal/port_mapping.py`（93 行）

当前只有 d2a（正向）桥接。Task 1 将重命名 + 新增 a2d。

### 4.4 `toffee/toffee/mixed_signal/mixed_signal_simulator.py`（90 行）

当前只有 `_apply_digital_to_analog()` (line 51-76)。Task 2 将新增双后端 `_apply_analog_to_digital()`。

### 4.5 `toffee/toffee/analog/ngspice_simulator.py`（672 行）

- `_on_send_data()` (line 305-344): trigger 后只设 `_next_sync_time`，未通知 asyncio
- `add_async_trigger()` (line 232-235): 注册 trigger，未创建 asyncio.Event
- Task 4 将修复

### 4.6 `toffee/toffee/analog/xyce_simulator.py`（148 行）

- `advance_to(time)` -> `_xyce.simulateUntil(time)`
- 缺失: setPauseTime、YADC 读取、硬编码路径
- Task 5 将修复

### 4.7 Xyce C API 改造状态

- `N_CIR_XyceCInterface.h:103`: `int xyce_setPauseTime(void ** ptr, double pauseTime);` -- 已声明
- `N_CIR_XyceCInterface.C:990-1005`: 已实现，注入 PAUSE breakpoint
- `xyce_interface.py`: 两个版本均缺少 `setPauseTime` Python 方法 -- Task 0 修复
- Xyce 原生 YADC API 已可用: `getADCMap()`, `getTimeStatePairsADC()`, `getTimeVoltagePairsADC()`, `setADCWidths()`

---

## 五、测试文件列表

| 文件 | 测试数 | 状态 | 需修改 |
|------|--------|------|--------|
| `tests/analog/test_ngspice_async_events.py` | ~4 | PASS | Task 4 新增测试 |
| `tests/analog/test_ngspice_lazysync.py` | ~3 | PASS | - |
| `tests/analog/test_ngspice_vsrc.py` | ~3 | PASS | - |
| `tests/analog/test_opamp_ngspice.py` | ~2 | PASS | Task 7 可能需改 |
| `tests/analog/test_rc_xyce.py` | ~2 | PASS | - |
| `tests/mixed_signal/test_mixed_signal_simulator.py` | ~6 | PASS | Task 2+3 修改 |
| `tests/mixed_signal/test_port_mapping.py` | ~5 | PASS | Task 1+3 修改 |
| `tests/mixed_signal/test_sar_adc_xyce.py` | ~2 | PASS | Task 3 修改 |
| `tests/mixed_signal/test_step_exact.py` | ~3 | PASS | Task 3 修改 |

**总计: 18 个测试当前全部通过。**

---

## 六、执行建议（推荐顺序）

**新 Agent 应按此顺序执行:**

1. **先读计划文档**: `docs/plans/2026-04-20-port-mapping-a2d-and-bidirectional-bridge.md`
2. **Task 0**: xyce_interface.py 补 setPauseTime 封装
3. **Task 1**: PortMapping 重命名 + A2D
4. **Task 2**: MixedSignalSimulator 双后端 A2D 桥接
5. **Task 3**: 同步修改所有测试文件
6. **Task 4**: ngspice trigger 通知 asyncio (lazy loop capture)
7. **Task 5**: Xyce setPauseTime + YADC + 路径清理
8. **Task 6**: Simulator 基类 events/next_event
9. **Task 7**: AnalogAgent 事件配置 (依赖 Task 6)
10. **Task 8**: 全部回归测试 + 提交

每个 Task 完成后运行 `pytest tests/analog/ tests/mixed_signal/ -v` 验证。

---

## 七、环境信息

```
Python: 3.10.12
pytest: 9.0.2
OS: Linux (WSL)
工作目录: /mnt/d/ongoingProjects/openEDA/toffee_project/toffee/
Git: master 分支，ahead of origin/master by 8 commits
```

---

## 八、快速启动命令

```bash
cd /mnt/d/ongoingProjects/openEDA/toffee_project/toffee

# 查看当前状态
git log --oneline -5
git status

# 运行全部模拟/混合信号测试
pytest tests/analog/ tests/mixed_signal/ -v

# 查看计划 (v2)
cat docs/plans/2026-04-20-port-mapping-a2d-and-bidirectional-bridge.md

# 查看本上下文
cat docs/context/CONTINUE_AFTER_RESTART.md
```
