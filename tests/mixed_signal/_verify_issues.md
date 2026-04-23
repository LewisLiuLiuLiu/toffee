## 验证报告

### 验证证据

```
$ grep -rn "bridge|BridgeSpec|ParamBridgeSpec|reverse_bridge|..." toffee/mixed_signal/ --include="*.py"
CLEAN - no old names in source

$ grep -rn "bridge|..." toffee/ tests/ --include="*.py" | grep -v d2a|a2d|D2A|A2D
tests/mixed_signal/test_mixed_signal_simulator.py:42:async def test_advance_applies_dac_bridge():
tests/mixed_signal/test_mixed_signal_simulator.py:102:async def test_advance_applies_param_bridge():
^ These are only test FUNCTION NAMES, not API usage. Cosmetic only, not a bug.

$ grep -rn "pass$|...$|NotImplementedError|TODO|FIXME" toffee/mixed_signal/ tests/mixed_signal/
tests/mixed_signal/test_mixed_signal_simulator.py:38: pass  (FakeXyce.close() - valid empty mock method)

$ grep "bare except|except:" toffee/mixed_signal/ --include="*.py"
NO BARE EXCEPTS - exception handling uses specific (RuntimeError, OSError, AttributeError)

$ python3 -m pytest tests/mixed_signal/ -v
============================== 28 passed in 0.98s ==============================
```

### 发现的问题

| 严重性 | 文件:行号 | 问题描述 | 状态 |
|--------|----------|----------|------|
| — | — | No bugs found | N/A |

**No real bugs were found.** All critical logic is correct:

### 验证矩阵

| Requirement | Evidence | Verdict |
|-------------|----------|---------|
| Old API names removed from source | `grep` on toffee/mixed_signal/ → CLEAN | ✅ PASS |
| No old spec classes (BridgeSpec, ParamBridgeSpec) | `hasattr` test confirms they don't exist | ✅ PASS |
| A2DSpec fields (digital_name, threshold=0.9, invert=False, yadc_device="") | Dataclass inspection + test_a2dspec_fields | ✅ PASS |
| YADC values used DIRECTLY (no threshold re-binarization) | test_yadc_value_not_thresholded with threshold=2.0 catches the bug | ✅ PASS |
| Safe invert logic (`0 if val else 1`, not `1 - val`) | test_invert_safe_with_nonbinary_yadc: YADC state=2, invert→0 not -1 | ✅ PASS |
| Threshold boundary (>=) | test_threshold_exact_boundary: voltage==threshold → 1 | ✅ PASS |
| Multiple YADC devices mapped correctly | test_multiple_yadc_devices: two ADCs with different states | ✅ PASS |
| YADC failure graceful fallback | test_yadc_failure_falls_back_to_threshold: RuntimeError → threshold | ✅ PASS |
| Exception handling is specific | `except (RuntimeError, OSError, AttributeError)` — not bare | ✅ PASS |
| Pin .value attribute support | test_a2d_writes_to_pin_value_attr | ✅ PASS |
| step_time validation | test_step_time_negative_raises, test_step_time_zero_raises | ✅ PASS |

### 验证测试

| 测试文件 | RED (先失败) | GREEN (后通过) |
|----------|-------------|----------------|
| _verify_test_a2d.py::test_yadc_value_not_thresholded | FAILED: `assert 0 == 1` (broke YADC to re-threshold) | PASSED |
| _verify_test_a2d.py::test_invert_safe_with_nonbinary_yadc | FAILED: `assert -1 == 0` (changed to `1 - val`) | PASSED |

### 测试结果

```
$ python3 -m pytest tests/mixed_signal/_verify_test_a2d.py -v
tests/mixed_signal/_verify_test_a2d.py::test_a2dspec_fields PASSED
tests/mixed_signal/_verify_test_a2d.py::test_a2dspec_defaults PASSED
tests/mixed_signal/_verify_test_a2d.py::test_no_old_api_names PASSED
tests/mixed_signal/_verify_test_a2d.py::test_no_old_spec_classes PASSED
tests/mixed_signal/_verify_test_a2d.py::test_threshold_exact_boundary PASSED
tests/mixed_signal/_verify_test_a2d.py::test_yadc_value_not_thresholded PASSED
tests/mixed_signal/_verify_test_a2d.py::test_invert_safe_with_nonbinary_yadc PASSED
tests/mixed_signal/_verify_test_a2d.py::test_invert_zero_becomes_one PASSED
tests/mixed_signal/_verify_test_a2d.py::test_multiple_yadc_devices PASSED
tests/mixed_signal/_verify_test_a2d.py::test_yadc_failure_falls_back_to_threshold PASSED
tests/mixed_signal/_verify_test_a2d.py::test_step_time_negative_raises PASSED
tests/mixed_signal/_verify_test_a2d.py::test_step_time_zero_raises PASSED
tests/mixed_signal/_verify_test_a2d.py::test_a2d_writes_to_pin_value_attr PASSED
============================== 13 passed in 0.18s ==============================

$ python3 -m pytest tests/mixed_signal/ -v
============================== 28 passed in 0.98s ==============================
```

### 修复的 commit

None needed — no bugs found.

### 未修复的问题

| 问题 | 原因 |
|------|------|
| Test function names still contain "bridge" (`test_advance_applies_dac_bridge`) | Cosmetic only — not a bug, functions test new d2a API correctly |
