# Project Status

> Last Updated: 2026-04-23 10:00
> Phase: 3-Execution (Batch 4 pending)

## Overview

**Goal:** 将 PortMapping 的 bridge/reverse_bridge 重命名为 d2a/a2d，并增加 analog-to-digital 反向桥接能力（双后端策略：Xyce YADC + ngspice 阈值 fallback），使 MixedSignalSimulator 支持双向混合信号通信。

**Context:** toffee 框架的混合信号模块目前只支持 digital-to-analog 单向桥接。需要增加 A2D 反向桥接，使模拟输出变化能通知数字侧。Xyce 后端有原生 YADC 设备可直接量化，ngspice 后端需要 Python 侧阈值判决配合 SendData 回调。

**Tech Stack:** Python 3.8+, pytest, toffee framework, NgSpice ctypes, Xyce ctypes, asyncio

## Requirements

### Requirement: API 命名重构

系统 MUST 将 PortMapping 中的 bridge/reverse_bridge 命名全量替换为 d2a/a2d，不保留旧名别名。

#### Scenario: D2A 声明式桥接
- **WHEN** 用户调用 `pm.d2a("dac_ctrl", "v_dac", scale=1.8)`
- **THEN** `pm.get_d2a("dac_ctrl")` 返回 `("v_dac", 1.8, 0.0)`

#### Scenario: 旧 API 不存在
- **WHEN** 用户调用 `pm.bridge(...)` 或 `pm.get_bridge(...)`
- **THEN** 抛出 AttributeError

### Requirement: A2D 反向桥接

系统 MUST 支持从模拟到数字的反向桥接声明，支持 Python 阈值判决和 Xyce YADC 两种后端。

#### Scenario: ngspice 阈值判决
- **GIVEN** PortMapping 声明了 `a2d("v(comp_out)", "comp_in", threshold=1.5)`
- **WHEN** MixedSignalSimulator.advance_to() 执行后模拟电压为 1.8V
- **THEN** 数字 pin comp_in 被驱动为 1

#### Scenario: Xyce YADC 读取
- **GIVEN** PortMapping 声明了 `a2d("v(sense)", "adc_out", yadc_device="YADC!ADC1")`
- **WHEN** MixedSignalSimulator.advance_to() 执行后调用 getTimeStatePairsADC()
- **THEN** 数字 pin adc_out 被驱动为 YADC 量化值

### Requirement: NgSpice 异步事件通知

系统 MUST 在 NgSpice trigger 检测到阈值穿越时，通过 call_soon_threadsafe 通知 asyncio 事件循环。asyncio loop 采用延迟捕获。

#### Scenario: Trigger 触发 asyncio Event
- **GIVEN** NgSpiceSimulator 注册了 threshold trigger
- **WHEN** C 回调线程检测到阈值穿越
- **THEN** asyncio Event "threshold_crossed" 被 set
- **AND** trigger handler 异常被 logging.debug 记录（不静默吞没）

### Requirement: Xyce setPauseTime 同步点

系统 MUST 支持通过 setPauseTime 在 simulateUntil 大步中插入中间同步检查点（非自动阈值检测）。

#### Scenario: setPauseTime 中间暂停
- **GIVEN** XyceSimulator 调用 set_pause_time(2e-9)
- **WHEN** simulateUntil(5e-9) 执行
- **THEN** 实际停止时间为 2e-9
- **AND** 再次调用 simulateUntil(5e-9) 到达 5e-9

### Requirement: Simulator 事件接口

系统 MUST 在 Simulator 基类提供 events property 和 next_event() 方法，AnalogAgent 通过此接口获取事件通知。

#### Scenario: AnalogAgent 使用 events
- **GIVEN** Simulator 子类实现了 events property
- **WHEN** AnalogAgent 初始化时传入 event_name="threshold_crossed"
- **THEN** AnalogAgent 使用该事件而非默认 clock_event

## Subtasks

### Batch 1: PortMapping 重构 + MixedSignalSimulator 适配

- [x] Task 1: PortMapping 重命名 bridge->d2a, 新增 A2DSpec 和 a2d()
  - **Covers:** Requirement: API 命名重构, Requirement: A2D 反向桥接
  - **Acceptance:** port_mapping.py 导出 D2ASpec, D2AParamSpec, A2DSpec; 旧 API 不存在
  - **Scope:** `toffee/mixed_signal/port_mapping.py`, `toffee/mixed_signal/__init__.py`

- [x] Task 2: MixedSignalSimulator 适配新命名 + _apply_analog_to_digital
  - **Covers:** Requirement: A2D 反向桥接
  - **Acceptance:** advance_to() 后 A2D 桥接正确驱动数字 pin
  - **Scope:** `toffee/mixed_signal/mixed_signal_simulator.py`

- [x] Task 3: 同步修改所有测试文件
  - **Covers:** 全部 Requirements 的测试覆盖
  - **Acceptance:** `pytest tests/mixed_signal/ -v` 全部 PASS
  - **Scope:** `tests/mixed_signal/test_port_mapping.py`, `tests/mixed_signal/test_mixed_signal_simulator.py`, `tests/mixed_signal/test_sar_adc_xyce.py`, `tests/mixed_signal/test_step_exact.py`

### Batch 2: 模拟器事件系统

- [x] Task 4: NgSpiceSimulator trigger 通知 asyncio（lazy loop + 日志）
  - **Covers:** Requirement: NgSpice 异步事件通知
  - **Acceptance:** trigger 触发后 asyncio Event 被 set; 异常被 logged
  - **Scope:** `toffee/analog/ngspice_simulator.py`, `tests/analog/test_ngspice_async_events.py`

- [x] Task 5: XyceSimulator 接入 setPauseTime + YADC 读取
  - **Covers:** Requirement: Xyce setPauseTime 同步点, Requirement: A2D 反向桥接 (YADC)
  - **Acceptance:** set_pause_time() + read_adc_states() 方法可用; 环境变量替代硬编码路径
  - **Scope:** `toffee/analog/xyce_simulator.py`, `tests/analog/test_xyce_pause_time.py`

### Batch 3: 事件接口 + AnalogAgent

- [x] Task 6: Simulator 基类 events/next_event + __event_loop
  - **Covers:** Requirement: Simulator 事件接口
  - **Acceptance:** Simulator.events 和 next_event() 可用; __event_loop 统一触发
  - **Scope:** `toffee/simulator.py`, `toffee/asynchronous.py`

- [x] Task 7: AnalogAgent 事件配置
  - **Covers:** Requirement: Simulator 事件接口
  - **Acceptance:** AnalogAgent 使用 simulator.events 获取事件
  - **Scope:** `toffee/analog/analog_agent.py` (corrected from plan's toffee/mixed_signal/agent.py)

### Batch 4: 全量回归

- [ ] Task 8: 全部回归测试
  - **Covers:** 全部 Requirements
  - **Acceptance:** `pytest tests/ -v` 全部 PASS
  - **Scope:** `tests/`

## Verification Results

| Batch | Task | Scenario Verified | Status | Method | Notes |
|-------|------|-------------------|--------|--------|-------|
| 1 | Task 1-3 | D2A Declarative Bridge | PASS | pytest | 11 port_mapping tests |
| 1 | Task 1-3 | Old API Not Existing | PASS | grep | Zero matches for old names |
| 1 | Task 1-3 | ngspice Threshold Decision | PASS | pytest | test_advance_applies_a2d_bridge |
| 1 | Task 1-3 | Xyce YADC Read | PARTIAL | pytest | YADC logic correct, XyceSimulator wrapper in Batch 2 |
| 2 | Task 4 | Trigger asyncio Event | PASS | pytest | 8 async event tests |
| 2 | Task 5 | setPauseTime 中间暂停 | PASS | pytest | mock tests for pause/YADC/ADCmap |
| 2 | Task 5 | read_adc_states() | PASS | pytest | 5 XyceSimulator tests |
| 3 | Task 6 | Simulator.events default | PASS | pytest | returns {"step": clock_event} |
| 3 | Task 6 | next_event() default | PASS | pytest | step(1) + return "step", no tick() |
| 3 | Task 6 | __event_loop unified set/clear | PASS | spec review | evt.set()/clear() after next_event() |
| 3 | Task 7 | AnalogAgent event_name | PASS | pytest | events.get() with fallback |
| 3 | Task 6-7 | __has_unwait_task compat | PASS | spec review | task name kept as "__clock_loop" |
| 3 | Task 6-7 | NgSpiceSimulator compat | PASS | spec review | events override no conflict |

## Execution Log

| Time | Phase | Subagent | Result | Notes |
|------|-------|----------|--------|-------|
| 2026-04-22 14:50 | Pre-workflow | code-executor | SUCCESS | Task 0: setPauseTime added to both xyce_interface.py |
| 2026-04-22 15:00 | Batch 1 | code-executor | SUCCESS | Tasks 1-3: 20 tests pass |
| 2026-04-22 15:10 | Batch 1 | general-purpose | PARTIAL | Spec: YADC path dead code (Batch 2 fix) |
| 2026-04-22 15:15 | Batch 1 | code-executor | SUCCESS | Fix YADC logic: batch-read + direct state |
| 2026-04-22 15:20 | Batch 1 | code-reviewer | PASS+FIXES | Quality: 7 issues, 5 fixed |
| 2026-04-22 15:25 | Batch 1 | code-executor | SUCCESS | Quality fixes: 27 tests pass |
| 2026-04-22 15:35 | Batch 2 | code-executor | SUCCESS | Tasks 4-5: 13 analog tests pass |
| 2026-04-22 15:45 | Batch 2 | general-purpose | PASS | Spec: 3/3 scenarios pass |
| 2026-04-22 15:45 | Batch 2 | code-reviewer | PASS+FIXES | Quality: 7 issues, 4 fixed |
| 2026-04-22 15:55 | Batch 2 | code-executor | SUCCESS | Quality fixes: 13 tests still pass |
| 2026-04-23 09:30 | Batch 3 | code-executor | SUCCESS | Tasks 6-7: 49 tests pass (8 new) |
| 2026-04-23 09:40 | Batch 3 | general-purpose | PASS | Spec: 6/6 scenarios pass |
| 2026-04-23 09:40 | Batch 3 | code-reviewer | PASS+FIXES | Quality: 7 issues; 2 fixed (vacuous test, silent drop) |

## Technical Decisions

- A2D 采用双后端策略：Xyce 用 YADC 原生机制，ngspice 用 Python 阈值 fallback
- setPauseTime 定位为预定时间点同步辅助，非自动阈值检测
- asyncio loop 采用延迟捕获（lazy capture），不在 __init__ 中捕获
- next_event() 只返回事件名，set/clear 统一由 __event_loop 完成
- 硬编码路径改为环境变量

## Known Issues

- MixedSignalSimulator._apply_analog_to_digital() 直接访问 self._analog._xyce (Issue #5 from Batch 1 Quality review) — 将通过 XyceSimulator.read_adc_states() 公开方法解决
- Pre-existing double-trigger: analog simulators' step() calls tick() internally, and __event_loop also does set/clear. This is the same behavior as old __clock_loop. Future fix: override next_event() in analog simulators to skip tick().
- AnalogAgent passes event.wait callable to Agent.__init__, triggering deprecation warning (pre-existing pattern)
