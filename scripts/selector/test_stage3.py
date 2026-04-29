"""Unit tests for Stage 3 score integration.

Run with::

    python3 -m scripts.selector.test_stage3

Covers the seven cases listed in the Stage 3 design proposal:

1. 全項目満点・mainstream=false                      → 100.00
2. 全項目満点・mainstream=true                       →  73.00
3. 全項目満点・mainstream=unknown(3)                 →  89.20
4. 全項目0点                                         →   0.00
5. 全項目5点・mainstream=unknown・penalty=-3         →  49.70
6. 全項目5点・mainstream=unknown・penalty=-5         →  47.70
7. 美意識2_machine が None（→ 6 fallback、警告フラグ） →  89.20

Tests 1-6 mirror the design proposal table verbatim. Test 7 verifies the
``missing_aesthetic_2_warning`` path called for in論点2 of the design
sign-off.
"""

from __future__ import annotations

import sys

from .stage3 import compute_final_score


def _check(
    label: str,
    entry: dict,
    expected_score: float,
    *,
    expected_missing: bool = False,
    tolerance: float = 0.01,
) -> bool:
    actual_score, actual_missing = compute_final_score(entry)
    score_ok = abs(actual_score - expected_score) <= tolerance
    missing_ok = actual_missing == expected_missing
    ok = score_ok and missing_ok
    sym = "✓" if ok else "✗"
    detail = f"got={actual_score:.2f}, expected={expected_score:.2f}"
    if expected_missing or actual_missing:
        detail += f", missing_a2={actual_missing} (expected {expected_missing})"
    print(f"  {sym} {label}: {detail}")
    return ok


def main() -> int:
    print("Stage 3 unit tests")
    print()

    pass_count = 0
    fail_count = 0

    # ----- 1: all-10s, mainstream=false (raw 5 → norm 10) -----
    e1 = {
        "美意識1": 10, "美意識3": 10, "美意識5": 10, "美意識6": 10, "美意識8": 10,
        "美意識2_machine": 5, "美意識4_penalty": 0,
    }
    if _check("01 all-10s, mainstream=false", e1, 100.00):
        pass_count += 1
    else:
        fail_count += 1

    # ----- 2: all-10s, mainstream=true (raw 0 → norm 0) -----
    e2 = {**e1, "美意識2_machine": 0}
    # weighted = 10*18 + 10*27 + 10*9 + 10*9 + 10*10 + 0*27 = 180+270+90+90+100 = 730
    # base = 73.00
    if _check("02 all-10s, mainstream=true", e2, 73.00):
        pass_count += 1
    else:
        fail_count += 1

    # ----- 3: all-10s, mainstream=unknown (raw 3 → norm 6) -----
    e3 = {**e1, "美意識2_machine": 3}
    # weighted = 180+270+90+90+100 + 6*27 = 730 + 162 = 892
    # base = 89.20
    if _check("03 all-10s, mainstream=unknown(3)", e3, 89.20):
        pass_count += 1
    else:
        fail_count += 1

    # ----- 4: all-zeros -----
    e4 = {
        "美意識1": 0, "美意識3": 0, "美意識5": 0, "美意識6": 0, "美意識8": 0,
        "美意識2_machine": 0, "美意識4_penalty": 0,
    }
    if _check("04 all-0s", e4, 0.00):
        pass_count += 1
    else:
        fail_count += 1

    # ----- 5: all-5s, mainstream=unknown, penalty=-3 -----
    # weighted = 5*18 + 5*27 + 5*9 + 5*9 + 5*10 + 6*27 = 90+135+45+45+50+162 = 527
    # base = 52.70, +(-3) = 49.70
    e5 = {
        "美意識1": 5, "美意識3": 5, "美意識5": 5, "美意識6": 5, "美意識8": 5,
        "美意識2_machine": 3, "美意識4_penalty": -3,
    }
    if _check("05 all-5s, m=3, penalty=-3", e5, 49.70):
        pass_count += 1
    else:
        fail_count += 1

    # ----- 6: all-5s, mainstream=unknown, penalty=-5 -----
    e6 = {**e5, "美意識4_penalty": -5}
    if _check("06 all-5s, m=3, penalty=-5", e6, 47.70):
        pass_count += 1
    else:
        fail_count += 1

    # ----- 7: missing 美意識2_machine (defaults to 6, warning flag set) -----
    e7 = {
        "美意識1": 10, "美意識3": 10, "美意識5": 10, "美意識6": 10, "美意識8": 10,
        "美意識2_machine": None, "美意識4_penalty": 0,
    }
    # Same numerical result as case 3 (norm 6), with warning flag set.
    if _check(
        "07 missing 美意識2 (defaults to 6, flag set)",
        e7, 89.20,
        expected_missing=True,
    ):
        pass_count += 1
    else:
        fail_count += 1

    print()
    print(f"=== {pass_count} passed, {fail_count} failed ===")
    return 0 if fail_count == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
