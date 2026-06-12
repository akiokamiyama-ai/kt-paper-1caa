"""Tribune 1 週間草稿生成 CLI（C38b, Sprint 9, 2026-06-09）。

Usage
-----

    # 明示的な日付範囲（W 集約の本道、W1 遡及生成にも使用）
    python -m scripts.notes.generate --start 2026-05-24 --end 2026-05-30 \\
                                     --label W1

    # ISO 週指定
    python -m scripts.notes.generate --week 2026-W23

    # LLM を呼ばずに入力を組み立てるだけ
    python -m scripts.notes.generate --start 2026-05-24 --end 2026-05-30 \\
                                     --label W1 --dry-run

出力
----
``data/notes/{label}.md`` に保存。``--label`` を省略すると、--week 指定時は
"2026-W23"、--start/--end 指定時は "{start}-to-{end}" 形式で自動生成。

セキュリティ
------------
- ANTHROPIC_API_KEY を環境変数から読み込む（scripts.lib.llm 経由）
- 神山さんコメント / 論考は ``<<<INPUT_BEGIN>>> ... <<<INPUT_END>>>`` で
  囲んで挿入し、prompt injection を防御（C57 と同パターン）
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

from . import prompts
from .extractor import load_day
from .models import DayEntry, GeneratedNote, NoteContext
from .style_loader import build_style_block_from_disk, load_style_cache

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
NOTES_DIR = PROJECT_ROOT / "data" / "notes"

DEFAULT_MAX_TOKENS = 8192  # 5000字目標、漢字含む 1 token ≈ 1.5字 → 余裕を持って 8K
DEFAULT_TEMPERATURE = 0.7

# C80b (Sprint 9, 2026-06-12, Fable review H2): ``--label`` を出力ファイル名に
# 直結する path traversal / 任意 .md 上書き対策。検証を save_note と
# _build_context の両方で行う多層防御。許可されるのは ASCII alphanumeric +
# underscore + ハイフンのみ。自動生成 label "W1" / "2026-W23" /
# "2026-05-24-to-2026-05-30" は全て通過する。
LABEL_PATTERN = re.compile(r"^[A-Za-z0-9_\-]+$")


def _validate_label(label: str) -> None:
    """``label`` が安全なファイル名構成要素か検査。

    Raises
    ------
    ValueError
        label が空 / 不正な文字を含む場合。``..`` や絶対パス区切り、
        改行 / NULL 等は全て弾く。
    """
    if not label:
        raise ValueError("label is empty")
    if not LABEL_PATTERN.fullmatch(label):
        raise ValueError(
            f"invalid label: {label!r} "
            f"(must match {LABEL_PATTERN.pattern}, "
            f"i.e. ASCII alphanumeric + underscore + hyphen only; "
            f"prevents path traversal / arbitrary .md overwrite)"
        )


# ---------------------------------------------------------------------------
# CLI args → date range / label
# ---------------------------------------------------------------------------

def _parse_iso_week(week_str: str) -> tuple[date, date]:
    """``2026-W23`` → (Mon, Sun) of that ISO week."""
    if not week_str:
        raise ValueError("empty week")
    try:
        year_str, w_part = week_str.split("-W")
        year = int(year_str)
        week = int(w_part)
    except (ValueError, IndexError) as e:
        raise ValueError(f"invalid --week format: {week_str!r} (expected YYYY-Wnn)") from e
    monday = datetime.strptime(f"{year}-W{week:02d}-1", "%G-W%V-%u").date()
    sunday = monday + timedelta(days=6)
    return monday, sunday


def _build_context(args: argparse.Namespace) -> NoteContext:
    if args.week:
        start, end = _parse_iso_week(args.week)
        label = args.label or args.week
    else:
        if not (args.start and args.end):
            raise ValueError("either --week or both --start/--end are required")
        start = date.fromisoformat(args.start)
        end = date.fromisoformat(args.end)
        if end < start:
            raise ValueError(f"--end {end} is before --start {start}")
        label = args.label or f"{start.isoformat()}-to-{end.isoformat()}"

    # C80b: 早期検証で CLI 入力ミスを起動直後に弾く（save_note でも再検証）。
    _validate_label(label)

    days: list[DayEntry] = []
    cur = start
    while cur <= end:
        days.append(load_day(cur))
        cur += timedelta(days=1)

    return NoteContext(start_date=start, end_date=end, label=label, days=days)


# ---------------------------------------------------------------------------
# Build LLM input + call
# ---------------------------------------------------------------------------

def build_user_message(ctx: NoteContext) -> str:
    blocks: list[str] = []
    for i, d in enumerate(ctx.days, start=1):
        blocks.append(prompts.render_day_block(
            day_index=i,
            date_iso=d.date.isoformat(),
            concept_name=d.concept_name,
            concept_essay=d.concept_essay,
            comment=d.comment,
        ))
    daily_blocks = "\n\n".join(blocks)
    return prompts.USER_TEMPLATE.format(
        start_date=ctx.start_date.isoformat(),
        end_date=ctx.end_date.isoformat(),
        daily_blocks=daily_blocks,
    )


def call_llm(ctx: NoteContext, *, model: str | None = None,
             max_tokens: int = DEFAULT_MAX_TOKENS,
             temperature: float = DEFAULT_TEMPERATURE,
             use_style_cache: bool = True) -> GeneratedNote:
    # Lazy import — extractor / models は LLM 不要、テスト容易性のため。
    from ..lib import llm

    user_msg = build_user_message(ctx)
    used_model = model or llm.DEFAULT_MODEL

    # C38b 第二弾 (2026-06-09): 神山さん note ブログを参照した文体ガイダンスを注入。
    style_block = build_style_block_from_disk() if use_style_cache else None
    system_prompt = prompts.build_system_prompt(style_block=style_block)

    response = llm.call_claude(
        system=system_prompt,
        user=user_msg,
        model=used_model,
        max_tokens=max_tokens,
        cache_system=True,
        temperature=temperature,
        tag="notes_generation",
    )

    return GeneratedNote(
        label=ctx.label,
        body=response.text.strip(),
        model=response.model,
        input_tokens=response.input_tokens,
        output_tokens=response.output_tokens,
        cache_creation_tokens=response.cache_creation_tokens,
        cache_read_tokens=response.cache_read_tokens,
        cost_usd=response.cost_usd,
    )


# ---------------------------------------------------------------------------
# Save
# ---------------------------------------------------------------------------

def save_note(note: GeneratedNote, *, notes_dir: Path = NOTES_DIR) -> Path:
    # C80b: 多層防御。_build_context で既に検証済だが、ライブラリ経由で
    # 不正 label が渡る経路を想定して再検証する。
    _validate_label(note.label)
    notes_dir.mkdir(parents=True, exist_ok=True)
    path = notes_dir / f"{note.label}.md"
    path.write_text(note.body + "\n", encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# CLI entry
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate a weekly note draft (C38b)",
    )
    # C80d (Sprint 9, 2026-06-12, Fable review L6): 旧仕様は
    # mutually_exclusive_group のメンバーが --week 1 個のみで排他が機能
    # していなかった（--week と --start/--end 併用時に --week が黙って勝つ）。
    # --start を group に加えて argparse 段階で併用を弾く。--end は --start
    # とセットなので別個に。
    g = parser.add_mutually_exclusive_group()
    g.add_argument("--week", help="ISO week, e.g. 2026-W23")
    g.add_argument("--start", help="Range start (YYYY-MM-DD); pair with --end")
    parser.add_argument("--end", help="Range end (YYYY-MM-DD); requires --start")
    parser.add_argument("--label", help="Output filename label (default auto)")
    parser.add_argument("--model", help="LLM model id (default: scripts.lib.llm.DEFAULT_MODEL)")
    parser.add_argument("--max-tokens", type=int, default=DEFAULT_MAX_TOKENS)
    parser.add_argument("--temperature", type=float, default=DEFAULT_TEMPERATURE)
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print the assembled prompt and exit; do not call LLM nor write file",
    )
    parser.add_argument(
        "--print", action="store_true",
        help="Also echo the generated body to stdout after saving",
    )
    parser.add_argument(
        "--no-style-cache", action="store_true",
        help="Skip the kamiyama_style.json injection (use bare system prompt only)",
    )
    args = parser.parse_args(argv)

    if not args.week and not (args.start and args.end):
        parser.error("either --week or both --start/--end are required")

    try:
        ctx = _build_context(args)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    # 入力サマリ
    print(f"[notes] label={ctx.label}", file=sys.stderr)
    print(f"[notes] range={ctx.start_date} -> {ctx.end_date}", file=sys.stderr)
    for d in ctx.days:
        e = len(d.concept_essay)
        c = len(d.comment)
        marker = " ★" if d.has_comment else ""
        print(f"  {d.date}  essay={e:4d}字  comment={c:4d}字  "
              f"concept={d.concept_name[:40]!r}{marker}", file=sys.stderr)

    # Style cache サマリ
    use_style = not args.no_style_cache
    if use_style:
        cache = load_style_cache()
        if cache:
            arts = cache.get("articles") or []
            print(
                f"[notes] style cache: {len(arts)} articles "
                f"(fetched {cache.get('fetched_at','?')})",
                file=sys.stderr,
            )
        else:
            print("[notes] style cache: not found, using bare prompt",
                  file=sys.stderr)
    else:
        print("[notes] style cache: disabled by --no-style-cache",
              file=sys.stderr)

    if args.dry_run:
        print("\n=== SYSTEM PROMPT (dry-run) ===\n", file=sys.stderr)
        style_block = build_style_block_from_disk() if use_style else None
        print(prompts.build_system_prompt(style_block=style_block))
        print("\n=== USER MESSAGE (dry-run) ===\n", file=sys.stderr)
        print(build_user_message(ctx))
        return 0

    note = call_llm(
        ctx,
        model=args.model,
        max_tokens=args.max_tokens,
        temperature=args.temperature,
        use_style_cache=use_style,
    )

    path = save_note(note)
    print(
        f"[notes] saved: {path} "
        f"(model={note.model} in={note.input_tokens} out={note.output_tokens} "
        f"cache_create={note.cache_creation_tokens} cache_read={note.cache_read_tokens} "
        f"cost=${note.cost_usd:.4f})",
        file=sys.stderr,
    )

    if args.print:
        print(note.body)

    return 0


if __name__ == "__main__":
    sys.exit(main())
