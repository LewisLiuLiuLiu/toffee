## Verification Report: Async Event Notification System

### Verification Evidence

```
$ grep -rn "^\s*pass$" toffee/analog/ngspice_simulator.py
256:                pass    # in _ensure_loop() RuntimeError handler — intentional
703:            pass        # in finish() try/except for ngSpice_Command(b"reset") — intentional

$ grep -rn "TODO\|FIXME" toffee/analog/ngspice_simulator.py toffee/analog/xyce_simulator.py toffee/simulator.py toffee/asynchronous.py
(no output — no TODO/FIXME markers)

$ python3 -m pytest tests/analog/ -v --tb=short
===== 25 passed in 1.38s =====

$ python3 -m pytest tests/analog/_verify_test_async_events.py -v
===== 28 passed in 0.34s =====

$ python3 -m pytest tests/ --ignore=tests/mixed_signal/test_sar_adc_xyce.py -v --tb=short
===== 2 failed (pre-existing test_bundle.py), 67 passed =====
```

### Design Contract Verification

| Contract | File:Line | Status | Evidence |
|----------|-----------|--------|----------|
| Lazy loop capture (not in __init__) | ngspice_simulator.py:197,250-256 | ✅ PASS | `_asyncio_loop = None` in init; `_ensure_loop()` uses `get_running_loop()` |
| Bounded deque (maxlen=100) | ngspice_simulator.py:199 | ✅ PASS | `deque(maxlen=100)` confirmed; overflow test verified |
| is_closed() guard | ngspice_simulator.py:367 | ✅ PASS | `not loop.is_closed()` check before `call_soon_threadsafe` |
| WARNING logging for errors | ngspice_simulator.py:373-375 | ✅ PASS | Uses `logging.getLogger("toffee.ngspice").warning(...)` |
| set_pause_time wraps setPauseTime | xyce_simulator.py:148-158 | ✅ PASS | Calls `_xyce.setPauseTime(pause_time)`, raises on result != 1 |
| read_adc_states parses YADC data | xyce_simulator.py:160-188 | ✅ PASS | Extracts names & latest states, handles errors gracefully |
| Env variables for Xyce paths | xyce_simulator.py:12-17 | ✅ PASS | Reads `XYCE_SHARE`, `XYCE_LIB` with defaults |
| events returns {"step": clock_event} | simulator.py:63-66 | ✅ PASS | Default property returns single-key dict |
| next_event calls step(1), NOT tick() | simulator.py:68-76 | ✅ PASS | Only `self.step(1)` + `return "step"` |
| __event_loop unified set/clear | asynchronous.py:176-200 | ✅ PASS | `evt.set()` / `evt.clear()` after `next_event()` |
| start_clock uses __event_loop | asynchronous.py:220 | ✅ PASS | `create_task(__event_loop(simulator))` |

### Discovered Issues

| Severity | File:Line | Description | Status |
|----------|-----------|-------------|--------|
| — | — | No production bugs found | — |

### Design Notes (not bugs)

| Item | Description | Impact |
|------|-------------|--------|
| NgSpice/Xyce step_time() calls tick() | When used via __event_loop → next_event() → step() → step_time() → tick(), the event gets set/cleared twice (once in tick, once in __event_loop). Harmless because both set/clear are synchronous with no await between them. | None — asyncio Event futures are resolved only once |
| threshold_crossed event not cleared by __event_loop | The trigger fires and sets the event via call_soon_threadsafe, but __event_loop only processes the "step" event. The threshold_crossed event stays set until manually cleared. | By design — would need NgSpice-specific next_event() override for full event-driven flow |
| Existing tests use `list` not `deque` for _pending_events | test_ngspice_async_events.py stubs use `sim._pending_events = []` instead of `deque(maxlen=100)`. Tests still work because `list.append()` and `deque.append()` share the same API. | Low — tests validate logic but not bounded capacity |

### Verification Tests

| Test File | RED (failure confirmed) | GREEN (all pass) |
|-----------|------------------------|-------------------|
| _verify_test_async_events.py | FAILED: `test_next_event_does_not_call_tick` correctly catches tick() injection | 28 passed in 0.34s |

### RED Phase Evidence

```
# Injected tick() into next_event():
$ python3 -m pytest tests/analog/_verify_test_async_events.py::test_next_event_does_not_call_tick -v
FAILED - AssertionError: next_event() must not call tick()
assert 1 == 0

# Restored code:
$ python3 -m pytest tests/analog/_verify_test_async_events.py -v
28 passed in 0.34s
```

### Test Results

```
$ python3 -m pytest tests/analog/_verify_test_async_events.py -v
tests/analog/_verify_test_async_events.py::test_ensure_loop_returns_running_loop PASSED
tests/analog/_verify_test_async_events.py::test_ensure_loop_idempotent PASSED
tests/analog/_verify_test_async_events.py::test_ensure_loop_no_running_loop PASSED
tests/analog/_verify_test_async_events.py::test_pending_events_is_deque_with_maxlen PASSED
tests/analog/_verify_test_async_events.py::test_pending_events_bounded_overflow PASSED
tests/analog/_verify_test_async_events.py::test_trigger_with_closed_loop_does_not_crash PASSED
tests/analog/_verify_test_async_events.py::test_trigger_with_none_loop_does_not_crash PASSED
tests/analog/_verify_test_async_events.py::test_trigger_handler_logs_warning_on_error PASSED
tests/analog/_verify_test_async_events.py::test_trigger_disarms_after_firing PASSED
tests/analog/_verify_test_async_events.py::test_trigger_does_not_fire_below_threshold PASSED
tests/analog/_verify_test_async_events.py::test_trigger_does_not_fire_twice PASSED
tests/analog/_verify_test_async_events.py::test_trigger_forces_sync_time PASSED
tests/analog/_verify_test_async_events.py::test_base_events_returns_step_key PASSED
tests/analog/_verify_test_async_events.py::test_base_events_only_step PASSED
tests/analog/_verify_test_async_events.py::test_next_event_calls_step PASSED
tests/analog/_verify_test_async_events.py::test_next_event_does_not_call_tick PASSED
tests/analog/_verify_test_async_events.py::test_next_event_return_type PASSED
tests/analog/_verify_test_async_events.py::test_xyce_set_pause_time_wraps_correctly PASSED
tests/analog/_verify_test_async_events.py::test_xyce_set_pause_time_raises_on_failure PASSED
tests/analog/_verify_test_async_events.py::test_xyce_read_adc_states_parses_correctly PASSED
tests/analog/_verify_test_async_events.py::test_xyce_read_adc_states_empty_data PASSED
tests/analog/_verify_test_async_events.py::test_xyce_read_adc_states_exception_returns_empty PASSED
tests/analog/_verify_test_async_events.py::test_xyce_read_adc_states_with_empty_pairs PASSED
tests/analog/_verify_test_async_events.py::test_xyce_env_variables PASSED
tests/analog/_verify_test_async_events.py::test_send_data_null_vdata PASSED
tests/analog/_verify_test_async_events.py::test_send_data_stores_node_voltage PASSED
tests/analog/_verify_test_async_events.py::test_ngspice_events_property PASSED
tests/analog/_verify_test_async_events.py::test_event_loop_function_exists PASSED
===== 28 passed in 0.34s =====

$ python3 -m pytest tests/analog/ -v
===== 25 passed in 1.38s =====
```

### Unfixed Issues

None — no production bugs were found.

### Summary

**PASS** — The async event notification system is correctly implemented. All 11 design contracts verified. All 53 analog tests pass (28 new verification + 25 existing). No bugs, stubs, or unimplemented code found.
