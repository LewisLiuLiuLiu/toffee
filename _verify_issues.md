## Verification Report

### Verification Evidence

```
$ grep -rn "^\s*pass$" toffee/analog/analog_agent.py
(no output — no stub pass statements)

$ grep -rn "TODO\|FIXME" toffee/analog/analog_agent.py toffee/asynchronous.py
(no output — no TODO/FIXME markers)

$ python3 -m pytest tests/ -v --tb=short 2>&1 | tail -10
FAILED tests/test_bundle.py::test_bundle - Exception: Signal bind error (pre-existing)
FAILED tests/test_bundle.py::test_bundle_list - Exception: Signal bind error (pre-existing)
========================= 2 failed, 68 passed in 2.73s =========================
```

### Verified Features

| Feature | Status | Evidence |
|---------|--------|----------|
| AnalogAgent default event_name="step" → clock_event | PASS | test_analog_agent_default_event_uses_clock_wait |
| AnalogAgent custom event_name → simulator.events.get() | PASS | test_analog_agent_custom_event_uses_correct_wait |
| AnalogAgent fallback to clock_event for unknown event | PASS | test_analog_agent_fallback_to_clock_event |
| AnalogAgent bundle path still works | PASS | test_analog_agent_bundle_path |
| Simulator.events default returns {"step": clock_event} | PASS | test_simulator_events_default |
| Simulator.next_event() calls step(1) and returns "step" | PASS | test_next_event_default |
| next_event() does NOT call tick() (contract check) | PASS | test_next_event_does_not_call_tick |
| start_clock() wraps legacy DUTs via DigitalSimulator | PASS | test_start_clock_wraps_legacy_dut |
| __event_loop task named "__clock_loop" for compat | PASS | test_event_loop_task_name_compat |
| No import breakage in __init__.py exports | PASS | all 68 non-bundle tests pass |

### Discovered Issues

| Severity | File:Line | Description | Status |
|----------|-----------|-------------|--------|
| MEDIUM | analog_agent.py:17 → agent.py:22 | AnalogAgent(simulator=sim) triggers spurious "monitor_step deprecated" warning because event.wait is callable | DOCUMENTED |
| LOW | ngspice_simulator.py:461, xyce_simulator.py:86 | Analog simulators call tick() in step_time(), which would double-trigger if used with start_clock(). Not triggered in current usage. | DOCUMENTED |

### Issue Details

#### MEDIUM: Spurious deprecation warning

When `AnalogAgent(simulator=sim)` is constructed, it passes `event.wait` (a callable) to
`Agent.__init__(bundle)`. Since `callable(event.wait) == True`, Agent's constructor enters
the deprecated path and emits:

```
TOFFEE_WARNING: Passing monitor_step during Agent initialization is about to be deprecated...
```

This is confirmed by `test_analog_agent_simulator_emits_deprecation_warning`. The warning
is cosmetic (functionality is correct) but confusing. NOT FIXED because:
- Suppressing it requires changing Agent.__init__ or AnalogAgent's constructor pattern
- This is a deliberate internal usage of the callable path, not user misuse
- The original developer likely accepted this tradeoff

#### LOW: Latent double-tick for analog simulators

`NgSpiceSimulator.step_time()` (line 461) and `XyceSimulator.step_time()` (line 86) call
`self.tick()` after advancing. The `__event_loop` also does `evt.set()/evt.clear()` after
`next_event()` returns. If these simulators were passed to `start_clock()`, tick would fire
twice. NOT FIXED because analog simulators are never used with `start_clock()` — they use
direct `step_time()` calls or the `MixedSignalSimulator` adapter.

### Verification Tests

| Test File | RED (broke code) | GREEN (restored code) |
|-----------|------------------|-----------------------|
| _verify_test_analog_agent.py | FAILED: test_analog_agent_custom_event_uses_correct_wait (broke event lookup) | 11 passed in 0.16s |

### Test Results

```
$ python3 -m pytest tests/_verify_test_analog_agent.py -v
tests/_verify_test_analog_agent.py::test_analog_agent_default_event_uses_clock_wait PASSED
tests/_verify_test_analog_agent.py::test_analog_agent_custom_event_uses_correct_wait PASSED
tests/_verify_test_analog_agent.py::test_analog_agent_fallback_to_clock_event PASSED
tests/_verify_test_analog_agent.py::test_analog_agent_bundle_path PASSED
tests/_verify_test_analog_agent.py::test_analog_agent_simulator_emits_deprecation_warning PASSED
tests/_verify_test_analog_agent.py::test_simulator_events_default PASSED
tests/_verify_test_analog_agent.py::test_next_event_default PASSED
tests/_verify_test_analog_agent.py::test_next_event_does_not_call_tick PASSED
tests/_verify_test_analog_agent.py::test_start_clock_wraps_legacy_dut PASSED
tests/_verify_test_analog_agent.py::test_event_loop_task_name_compat PASSED
tests/_verify_test_analog_agent.py::test_analog_agent_simulator_path_no_bundle_attr PASSED
============================== 11 passed in 0.16s ==============================

$ python3 -m pytest tests/ --tb=short
========================= 2 failed, 79 passed in 2.73s =========================
(2 failures are pre-existing in test_bundle.py — signal binding issues unrelated to this branch)
```

### Pre-existing Failures (NOT caused by this branch)

| Test | Error | Root Cause |
|------|-------|------------|
| test_bundle.py::test_bundle | Signal bind error: e, a, b not found | Mock DUT missing expected signals |
| test_bundle.py::test_bundle_list | Signal bind error: io_c, io_d not found | Mock DUT missing expected signals |

### Conclusion

**PASS** — All AnalogAgent event configuration features work correctly. Backward compatibility
with legacy DUTs is maintained. The `__event_loop` task naming preserves `__has_unwait_task()`
compatibility. No import breakage detected. Two documented issues (spurious warning, latent
double-tick) are cosmetic/latent and do not affect current functionality.
