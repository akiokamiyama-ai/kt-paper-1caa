"""Phase 3 案 C 統合型 1 面再設計のエントリポイント（2026-05-23）.

仕様：phase3_directive_v2.md

実行モデル：
1. 通常運用（cron）:
   a. ``scripts.regen_front_page_v2.main(args)`` を delegate 実行（全 6 面を
      従来通り build & archive 書き込み）。
   b. v3 が適用可能（monthly_pivotal.json に該当週あり、当該週 article が
      整っている）なら、archive HTML の page-one セクションを v3 版に
      surgical swap + CSS inject + 土曜は来週予告セクションを差し込み。
   c. v3 が適用不可（月次選定未了、週欠落、例外発生）なら v2 出力のまま。
      → これがフェイルセーフ（仕様 §10）。

2. dry-run:
   - v2 を呼ばない。v3 page-one セクションのみを単体 HTML として
     /tmp/v3_dryrun/<date>_v3.html に書き出す（CSS + fonts つき）。
   - 実 LLM 呼び出しは行う（コスト発生）。
   - --history-path / --comments-dir でテスト用ディレクトリを差し替え可能。

v3 swap は in-memory で組み立ててから atomic 書き戻し。途中で失敗しても
archive ファイルは v2 状態のまま保たれる。
"""

from __future__ import annotations

import argparse
import importlib
import sys
import traceback
from dataclasses import asdict
from datetime import date
from pathlib import Path

from .page1_v3.comments_reader import DEFAULT_COMMENTS_DIR, load_week_comments
from .page1_v3.essay_generator import EssayResult, generate_essay
from .page1_v3.history import DEFAULT_HISTORY_PATH, load_week_essays, save_essay
from .page1_v3.monthly_pivotal import (
    DEFAULT_PIVOTAL_PATH,
    WeekContext,
    find_next_week,
    find_week_for_date,
    load_monthly_pivotal,
)
from .page1_v3.next_week_preview import build_next_week_preview
from .page1_v3.renderer import (
    PAGE_ONE_V3_CSS,
    inject_page_one_v3_css,
    render_page_one_v3,
)
from .page1_v3.saturday_responder import SaturdayResult, generate_saturday_response

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ARCHIVE_DIR = PROJECT_ROOT / "archive"


# ============================================================================
# CLI
# ============================================================================


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="regen_front_page_v3",
        description=(
            "Phase 3 案 C 統合型 1 面再設計。通常は v2 を呼んでから page-one を "
            "v3 に swap、dry-run では v3 単体 preview を /tmp に出力。"
        ),
    )
    p.add_argument("--date", help="ISO date (YYYY-MM-DD), defaults to today")
    p.add_argument("--dry-run", action="store_true",
                   help="v2 を呼ばず v3 単体 HTML を /tmp/v3_dryrun/ に出力")
    p.add_argument("--pivotal-path", help="data/monthly_pivotal.json 上書きパス")
    p.add_argument("--history-path", help="logs/page1_v3_history.json 上書きパス")
    p.add_argument("--comments-dir", help="data/comments/ 上書きディレクトリ")
    p.add_argument("--dry-run-out", default="/tmp/v3_dryrun",
                   help="dry-run 出力ディレクトリ（デフォルト: /tmp/v3_dryrun）")
    p.add_argument("--save-history-in-dryrun", action="store_true",
                   help="dry-run でも save_essay で履歴に積む（7 日連続テスト用）")
    return p


def main(argv: list[str] | None = None) -> int:
    # Pre-parse own args, leave the rest for v2.
    known, unknown = _build_parser().parse_known_args(argv)
    target = _parse_target_date(known.date)
    if target is None:
        return 1

    if known.dry_run:
        return _run_dryrun(target, known)

    return _run_production(target, known, v2_passthrough_argv=unknown)


def _parse_target_date(s: str | None) -> date | None:
    if s:
        try:
            return date.fromisoformat(s)
        except ValueError:
            print(f"[page1_v3] invalid --date {s!r}", file=sys.stderr)
            return None
    return date.today()


# ============================================================================
# Production: v2 → v3 swap
# ============================================================================


def _run_production(
    target_date: date,
    args: argparse.Namespace,
    v2_passthrough_argv: list[str],
) -> int:
    """v2 main を呼んで archive を生成、その上で page-one を v3 に swap.

    v2 main が rc != 0 で返したらそのまま rc を返す（v3 swap せず）。
    v3 swap 自体が例外を投げた場合も v2 出力はそのまま残し、rc=0 を返す
    （フェイルセーフ）。
    """
    print(
        f"[page1_v3] === production run for {target_date.isoformat()} ===",
        file=sys.stderr,
    )

    # 1. v2 main を delegate 実行
    regen_v2 = importlib.import_module(__package__ + ".regen_front_page_v2")
    # v2 にも --date を伝える（明示的に、unknown 任せにしない）
    v2_argv = ["--date", target_date.isoformat()] + list(v2_passthrough_argv)
    rc = regen_v2.main(v2_argv)
    if rc != 0:
        print(f"[page1_v3] v2 main returned rc={rc}, no v3 swap", file=sys.stderr)
        return rc

    # 2. v3 swap（失敗しても v2 出力のまま）
    try:
        applied = _try_v3_swap(target_date, args)
    except Exception as e:  # noqa: BLE001
        print(f"[page1_v3] v3 swap exception {type(e).__name__}: {e}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        print("[page1_v3] leaving v2 output as-is", file=sys.stderr)
        return 0

    if not applied:
        print("[page1_v3] v3 not applicable (未投入週など), v2 output stands",
              file=sys.stderr)
    else:
        print("[page1_v3] v3 page-one swap applied successfully", file=sys.stderr)
    return 0


def _try_v3_swap(target_date: date, args: argparse.Namespace) -> bool:
    """Returns True if v3 swap was applied. False = v3 not applicable (graceful)."""
    pivotal_path = Path(args.pivotal_path) if args.pivotal_path else DEFAULT_PIVOTAL_PATH
    history_path = Path(args.history_path) if args.history_path else DEFAULT_HISTORY_PATH
    comments_dir = Path(args.comments_dir) if args.comments_dir else DEFAULT_COMMENTS_DIR

    monthly = load_monthly_pivotal(pivotal_path)
    week = find_week_for_date(target_date, monthly)
    if week is None:
        return False

    result, next_preview_html = _generate_main_section(
        week, target_date, monthly, history_path, comments_dir,
    )

    archive_path = _archive_path(target_date)
    if not archive_path.exists():
        print(f"[page1_v3] archive missing: {archive_path}, can't swap", file=sys.stderr)
        return False

    html = archive_path.read_text(encoding="utf-8")
    if '<section class="page page-one">' not in html:
        # 既に v3 化済 or v2 構造が変わっている → no-op
        print("[page1_v3] page-one v2 marker not found, skipping swap",
              file=sys.stderr)
        return False

    v3_section = render_page_one_v3(
        target_date, week, result, next_preview_html,
    )
    new_html = _swap_page_one(html, v3_section)
    new_html = inject_page_one_v3_css(new_html)
    archive_path.write_text(new_html, encoding="utf-8")
    return True


def _swap_page_one(html: str, v3_section: str) -> str:
    """v2 の ``<section class="page page-one">...</section>`` を v3 に置換."""
    start_marker = '<section class="page page-one">'
    start = html.find(start_marker)
    if start == -1:
        raise RuntimeError("v2 page-one section not found")
    end = html.find("</section>", start)
    if end == -1:
        raise RuntimeError("v2 page-one section end not found")
    end += len("</section>")
    return html[:start] + v3_section + html[end:]


def _archive_path(target_date: date) -> Path:
    return ARCHIVE_DIR / f"{target_date.isoformat()}.html"


# ============================================================================
# v3 page-one section build
# ============================================================================


def _generate_main_section(
    week: WeekContext,
    target_date: date,
    monthly: dict,
    history_path: Path,
    comments_dir: Path,
    *,
    save_history: bool = True,
) -> tuple[EssayResult | SaturdayResult, str | None]:
    """日-金 → essay_generator、土 → saturday_responder.

    Returns (result, next_week_preview_html)。次週予告は土曜のみ非 None。
    """
    past_essays = load_week_essays(week, history_path=history_path)

    if week.angle_key == "response":
        # 土曜
        comments = load_week_comments(week, comments_dir=comments_dir)
        result = generate_saturday_response(week, past_essays, comments)
        next_week = find_next_week(week, monthly)
        preview = build_next_week_preview(next_week)
        return result, preview

    # 日-金
    essay = generate_essay(week, target_date, past_essays=past_essays)
    if save_history:
        save_essay(week, target_date, essay, history_path=history_path)
    return essay, None


# ============================================================================
# Dry-run: standalone preview
# ============================================================================


_STANDALONE_TMPL = """<!doctype html>
<html lang="ja"><head>
<meta charset="utf-8">
<title>Page 1 v3 dry-run — {date}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Noto+Serif+JP:wght@400;600;700&family=Playfair+Display:wght@400;700&display=swap" rel="stylesheet">
<style>
body {{ max-width: 1100px; margin: 24px auto; padding: 0 20px;
       font-family: 'Noto Serif JP', serif; color: #222; }}
.dryrun-meta {{ background: #fffae6; border: 1px solid #e0d68a;
                padding: 8px 14px; margin-bottom: 16px;
                font-family: monospace; font-size: 12px; }}
{css}
</style>
</head><body>
<div class="dryrun-meta">dry-run preview: {date} ({day_label} {angle}) — {meta}</div>
{section}
</body></html>"""


def _run_dryrun(target_date: date, args: argparse.Namespace) -> int:
    """v2 を呼ばず v3 セクションだけ単体 HTML を /tmp に書き出す."""
    pivotal_path = Path(args.pivotal_path) if args.pivotal_path else DEFAULT_PIVOTAL_PATH
    history_path = Path(args.history_path) if args.history_path else DEFAULT_HISTORY_PATH
    comments_dir = Path(args.comments_dir) if args.comments_dir else DEFAULT_COMMENTS_DIR
    out_dir = Path(args.dry_run_out)
    out_dir.mkdir(parents=True, exist_ok=True)

    monthly = load_monthly_pivotal(pivotal_path)
    week = find_week_for_date(target_date, monthly)
    if week is None:
        print(
            f"[dry-run] {target_date.isoformat()}: 該当週なし（v2 fallback 扱い）",
            file=sys.stderr,
        )
        return 0

    print(
        f"[dry-run] {target_date.isoformat()} ({week.day_label} {week.angle_label_jp}) "
        f"/ W: {week.theme}",
        file=sys.stderr,
    )

    result, preview_html = _generate_main_section(
        week, target_date, monthly, history_path, comments_dir,
        save_history=args.save_history_in_dryrun,
    )

    section = render_page_one_v3(target_date, week, result, preview_html)
    standalone = _STANDALONE_TMPL.format(
        date=target_date.isoformat(),
        day_label=week.day_label,
        angle=week.angle_label_jp,
        meta=_dry_run_meta(result),
        css=PAGE_ONE_V3_CSS,
        section=section,
    )
    out_path = out_dir / f"{target_date.isoformat()}_v3.html"
    out_path.write_text(standalone, encoding="utf-8")
    print(f"  → {out_path} ({_dry_run_meta(result)})", file=sys.stderr)
    return 0


def _dry_run_meta(result: EssayResult | SaturdayResult) -> str:
    bits = []
    is_fb = bool(getattr(result, "is_fallback", False))
    if is_fb:
        bits.append("⚠ fallback")
    if hasattr(result, "cost_usd"):
        bits.append(f"cost ${result.cost_usd:.4f}")
    if hasattr(result, "digest_cost_usd") and result.digest_cost_usd:
        bits.append(f"digest ${result.digest_cost_usd:.4f}")
    if isinstance(result, EssayResult):
        bits.append(f"body {len(result.body)}字")
    elif isinstance(result, SaturdayResult):
        bits.append(f"digest {len(result.comments_digest)}字 / response {len(result.response_body)}字")
    return " | ".join(bits) if bits else "(meta なし)"


if __name__ == "__main__":
    sys.exit(main())
