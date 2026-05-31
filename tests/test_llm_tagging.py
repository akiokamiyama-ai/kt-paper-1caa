"""Unit tests for LLM call tagging (Sprint 6 Phase 1).

record_call() に tag 引数が渡されたとき、calls エントリに ``"tag"`` フィールドが
含まれることを確認。後方互換のため、tag 未指定時は ``"untagged"`` が記録される。

Run::

    python3 -m tests.test_llm_tagging
"""

from __future__ import annotations

import json
import sys
import tempfile
from datetime import date
from pathlib import Path
from unittest.mock import patch

from scripts.lib import llm_usage

PASS = 0
FAIL = 0


def _check(label: str, condition: bool, detail: str = "") -> bool:
    global PASS, FAIL
    sym = "✓" if condition else "✗"
    line = f"  {sym} {label}"
    if detail:
        line += f"  ({detail})"
    print(line)
    if condition:
        PASS += 1
    else:
        FAIL += 1
    return condition


def test_record_call_with_tag():
    """tag 引数を渡すと、calls エントリに含まれる."""
    with tempfile.TemporaryDirectory() as tmp:
        log_dir = Path(tmp)
        with patch.object(llm_usage, "LOG_DIR", log_dir):
            llm_usage.record_call(
                "claude-sonnet-4-6", 100, 50,
                today=date(2026, 5, 10),
                tag="page2.step1",
            )
            log_file = log_dir / "llm_usage_2026-05-10.json"
            data = json.loads(log_file.read_text())
            entry = data["calls"][0]
            _check(
                "a1 tag='page2.step1' が calls エントリに記録される",
                entry.get("tag") == "page2.step1",
                f"got tag={entry.get('tag')!r}",
            )


def test_record_call_default_untagged():
    """tag 未指定時は 'untagged' が記録される（後方互換）."""
    with tempfile.TemporaryDirectory() as tmp:
        log_dir = Path(tmp)
        with patch.object(llm_usage, "LOG_DIR", log_dir):
            llm_usage.record_call(
                "claude-sonnet-4-6", 100, 50,
                today=date(2026, 5, 10),
            )
            log_file = log_dir / "llm_usage_2026-05-10.json"
            data = json.loads(log_file.read_text())
            entry = data["calls"][0]
            _check(
                "a2 tag 未指定時は 'untagged'",
                entry.get("tag") == "untagged",
                f"got tag={entry.get('tag')!r}",
            )


def test_record_call_multiple_tags():
    """複数の tag が混在する run でも、各 entry が正しく記録される."""
    with tempfile.TemporaryDirectory() as tmp:
        log_dir = Path(tmp)
        with patch.object(llm_usage, "LOG_DIR", log_dir):
            for tag, model, in_tok, out_tok in [
                ("page1.lead_deck", "claude-sonnet-4-6", 200, 80),
                ("stage2.batch", "claude-sonnet-4-6", 1500, 600),
                ("editorial", "claude-sonnet-4-6", 300, 100),
            ]:
                llm_usage.record_call(
                    model, in_tok, out_tok,
                    today=date(2026, 5, 10),
                    tag=tag,
                )
            log_file = log_dir / "llm_usage_2026-05-10.json"
            data = json.loads(log_file.read_text())
            tags = [c.get("tag") for c in data["calls"]]
            _check(
                "a3 3 件の tag が正しい順序で記録される",
                tags == ["page1.lead_deck", "stage2.batch", "editorial"],
                f"got tags={tags}",
            )


def test_call_sites_use_known_tags():
    """全呼び出し箇所が、規定の tag を使っていることを grep で確認.

    Phase A (Sprint 8, 2026-06-01): tag 命名規約整理
    - "stage2" → "stage2.batch" （batched evaluation を明示）
    - todays_headlines は LLM_SUMMARY_TAG="page2.headlines_summary" を使用、
      tag= リテラルとしては検査しない（定数経由のため）。
    """
    expected_tags = {
        "scripts/selector/page2.py": ["page2.step1", "page2.step2"],
        "scripts/selector/stage2.py": ["stage2.batch"],
        "scripts/page1/lead_deck_writer.py": ["page1.lead_deck"],
        "scripts/selector/why_important.py": ["page1.why_important"],
        "scripts/editorial/editorial_writer.py": ["editorial"],
        "scripts/page4/concept_writer.py": ["page4.concept"],
        "scripts/page6/cooking_generator.py": ["page6.cooking"],
        "scripts/page6/leisure_recommender.py": ["page6.leisure"],
    }
    project_root = Path(__file__).resolve().parent.parent
    all_ok = True
    for rel_path, tags in expected_tags.items():
        text = (project_root / rel_path).read_text()
        for tag in tags:
            present = f'tag="{tag}"' in text
            if not present:
                all_ok = False
                _check(
                    f"b {rel_path} で tag='{tag}' が見つからない",
                    False,
                )
    _check("b 全 9 呼び出し箇所が規定の tag を使う", all_ok)


def main() -> int:
    print("LLM call tagging tests (Sprint 6 Phase 1, 2026-05-10)")
    print()
    print("(a) record_call が tag を受け取って記録:")
    test_record_call_with_tag()
    test_record_call_default_untagged()
    test_record_call_multiple_tags()
    print()
    print("(b) 全呼び出し箇所が規定の tag を使う:")
    test_call_sites_use_known_tags()
    print()
    print(f"=== {PASS} passed, {FAIL} failed ===")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
