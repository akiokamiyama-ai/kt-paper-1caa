"""Shadow-mode dispatch for Stage 2 (C85 Sub-Step 6, Phase B Step 4).

3 つの mode を環境変数 ``TRIBUNE_STAGE2_MODE`` で切替する wrapper。**caller
側は ``run_stage2_with_mode`` 1 関数だけ呼べばよく**、shadow mode の
artifact 出力もここで処理する。

Mode:
- ``"legacy"`` (default): 従来通り、全件 Sonnet
- ``"shadow"`` : legacy + layered を **両方実行**、layered 結果は artifact 化
  のみ（採用には legacy 結果を使う）
- ``"layered"``: layered モード単独、採用にも layered 結果を使う

設計
----

shadow log は ``logs/stage2_shadow_YYYY-MM-DD.json`` に caller 別 dict で蓄積。
複数 caller（page1_master / page3）が同日複数 entry を書き込むため、
ファイルは追記型（既存内容を読み込んで該当 caller を上書き → 書き戻し）。

採用パターンの観察に使うのは ``legacy_top_30`` / ``layered_top_30`` URL list +
``overlap_count`` / ``overlap_ratio``。神山さん artifact レビュー用。
"""

from __future__ import annotations

import json
import os
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .stage2 import (
    LayerConfig,
    Stage2Result,
    run_stage2,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
LOG_DIR = PROJECT_ROOT / "logs"

# C88 (Sprint 10, 2026-06-16): GHA runner は UTC のため ``date.today()`` を直接
# 使うと、cron 起動 17:37 UTC + 3h 遅延 = 約 20:38 UTC ≒ JST 翌日 05:38 でも
# UTC 日付がまだ前日のままとなり、shadow log ファイル名と紙面 archive 日付が
# 1 日ずれる事故が起きていた（6/16 朝の artifact stage2_shadow_2026-06-15.json
# が実は 6/16 朝刊分）。``scripts/lib/llm_usage.py`` と同じ JST anchor を採用し、
# 日付を「Tribune の編集日」と一致させる。
_JST = ZoneInfo("Asia/Tokyo")


def _jst_today() -> date:
    """Return today's date in JST (Tribune's editorial day, C88)."""
    return datetime.now(_JST).date()

# 環境変数名（GHA workflow で指定可能）
ENV_MODE = "TRIBUNE_STAGE2_MODE"
# C86 (Sprint 10, 2026-06-15): "shadow_page1_only" モード追加。6/15 cron で
# 全 caller shadow (mode="shadow") が 90 分 timeout 強制 cancel された経験を
# 受けて、page1_master のみ shadow + 他 caller は legacy という軽量化モードを
# 用意する。stage2.batch 全体の 69% を占める master batch だけ観察すれば
# overlap_ratio / cost 効果は捕捉できる（Phase B Step 1 コスト分析参照）。
#
# C93 (Sprint 10, 2026-06-22): "layered_page1" モード追加。Phase B 本番切替の
# 軽量版で、page1_master のみ恒久 layered、他 caller は legacy。shadow 観察
# 6 日（C92）で安全性が立証された範囲のみ切替えるための保守的な mode。
# 全 caller layered の "layered" モードは将来（C94 で page3 拡張等）に取って
# おく。
VALID_MODES = (
    "legacy", "shadow", "shadow_page1_only", "layered_page1", "layered",
)
DEFAULT_MODE = "legacy"

# C86: shadow_page1_only モードで shadow を走らせる caller の allowlist。
# 将来 page3 等を追加したくなったら本セットを拡張。
SHADOW_PAGE1_ONLY_CALLERS: frozenset[str] = frozenset({"page1_master"})

# C93: layered_page1 モードで layered を走らせる caller の allowlist。
# shadow_page1_only と同じ caller セット（観察と本番切替の対称性を保つ）。
LAYERED_PAGE1_CALLERS: frozenset[str] = frozenset({"page1_master"})

# shadow log 採用パターン比較用の top-N
SHADOW_TOP_N = 30


def get_stage2_mode() -> str:
    """Return current Stage 2 mode from env var, fallback to legacy.

    不正値が指定された場合は ``DEFAULT_MODE`` (legacy) に fallback して stderr
    に警告を出す。神山さんが env var を typo した時の安全弁。
    """
    raw = os.environ.get(ENV_MODE, DEFAULT_MODE).strip().lower()
    if raw not in VALID_MODES:
        print(
            f"[stage2_shadow] WARN: invalid {ENV_MODE}={raw!r}, "
            f"fallback to {DEFAULT_MODE!r}",
            file=sys.stderr,
        )
        return DEFAULT_MODE
    return raw


def run_stage2_with_mode(
    articles: list[dict],
    *,
    caller: str,
    layer_config: LayerConfig | None = None,
    mode: str | None = None,
    shadow_log_path: Path | None = None,
    **kwargs: Any,
) -> Stage2Result:
    """Dispatch Stage 2 by mode and write shadow log when applicable.

    Parameters
    ----------
    articles :
        Stage 1 通過済の article dict 配列。
    caller :
        ``run_stage2`` の caller 識別子。``KNOWN_CALLERS`` 参照。
    layer_config :
        shadow / layered mode で使う設定。None なら default ``LayerConfig(enabled=True)``。
    mode :
        明示指定（テスト用）。None なら ``TRIBUNE_STAGE2_MODE`` 環境変数。
    shadow_log_path :
        shadow log の出力先（テスト用に override 可）。デフォルトは
        ``logs/stage2_shadow_YYYY-MM-DD.json``。
    **kwargs :
        ``run_stage2`` の追加 kwargs（batch_size / model / max_tokens 等）。

    Returns
    -------
    Stage2Result
        - legacy mode: legacy 結果
        - shadow mode: **legacy 結果**（layered は artifact のみ）
        - layered mode: layered 結果
    """
    effective_mode = (mode or get_stage2_mode()).lower()

    if effective_mode == "layered":
        cfg = layer_config or LayerConfig(enabled=True)
        return run_stage2(articles, layer_config=cfg, caller=caller, **kwargs)

    # C93: layered_page1 は対象 caller のみ恒久 layered、他 caller は legacy。
    # shadow ではなく本番切替モードなので、採用結果も layered。
    if effective_mode == "layered_page1":
        if caller in LAYERED_PAGE1_CALLERS:
            cfg = layer_config or LayerConfig(enabled=True)
            return run_stage2(
                articles, layer_config=cfg, caller=caller, **kwargs,
            )
        # else: 対象外 caller → legacy 経路へ fall through
        return run_stage2(
            articles, layer_config=None, caller=caller, **kwargs,
        )

    # C86: shadow_page1_only は対象 caller のみ shadow、他 caller は legacy。
    # mode を「実質的に shadow か否か」に正規化する。
    run_shadow = False
    if effective_mode == "shadow":
        run_shadow = True
    elif effective_mode == "shadow_page1_only":
        if caller in SHADOW_PAGE1_ONLY_CALLERS:
            run_shadow = True
        # else: 対象外 caller → legacy 経路へ fall through

    if run_shadow:
        # 1. legacy run（採用に使う）
        legacy_result = run_stage2(
            articles, layer_config=None, caller=caller, **kwargs,
        )
        # 2. layered run（shadow、artifact 化のみ）
        cfg = layer_config or LayerConfig(enabled=True)
        layered_result = run_stage2(
            articles, layer_config=cfg, caller=caller, **kwargs,
        )
        # 3. shadow log
        try:
            write_shadow_comparison(
                legacy_result, layered_result,
                caller=caller, articles=articles,
                path=shadow_log_path,
            )
        except Exception as e:  # noqa: BLE001
            print(
                f"[stage2_shadow] WARN: shadow log write failed: "
                f"{type(e).__name__}: {e}",
                file=sys.stderr,
            )
        # 4. 採用は legacy 結果
        return legacy_result

    # legacy mode（デフォルト）または shadow_page1_only で対象外 caller
    return run_stage2(articles, layer_config=None, caller=caller, **kwargs)


def _top_n_urls_by_final_score(
    result: Stage2Result, n: int = SHADOW_TOP_N,
) -> list[str]:
    """Return up to ``n`` URLs sorted by final_score descending.

    final_score が None / 未設定の場合は 0 として扱う（採用 pool に届く前なので
    pre-final_score の評価メタとしてアテにせず、観察用にラフな ranking のみ）。
    """
    entries = []
    for url, e in result.evaluations_by_url.items():
        fs = e.get("final_score")
        if fs is None:
            # 美意識重み付き合計の近似値を計算（partial sort の fallback）
            scores = e
            try:
                fs = (
                    scores.get("美意識1", 0) * 1.8
                    + scores.get("美意識3", 0) * 2.7
                    + scores.get("美意識5", 0) * 0.9
                    + scores.get("美意識6", 0) * 0.9
                    + scores.get("美意識8", 0) * 1.0
                    + (scores.get("美意識2_machine") or 0)
                )
            except (TypeError, ValueError):
                fs = 0
        entries.append((float(fs or 0), url))
    entries.sort(key=lambda x: x[0], reverse=True)
    return [url for _, url in entries[:n]]


def _count_evaluation_modes(result: Stage2Result) -> dict[str, int]:
    """Count entries by evaluation_mode for shadow log."""
    counts: dict[str, int] = {}
    for e in result.evaluations_by_url.values():
        mode = e.get("evaluation_mode") or "legacy_sonnet"
        counts[mode] = counts.get(mode, 0) + 1
    return counts


def _count_layers(result: Stage2Result) -> dict[str, int]:
    """Count entries by layer (1/2/3 or 'unspecified' for legacy)."""
    counts: dict[str, int] = {}
    for e in result.evaluations_by_url.values():
        lyr = e.get("layer")
        key = f"layer_{lyr}" if lyr is not None else "layer_unspecified"
        counts[key] = counts.get(key, 0) + 1
    return counts


def build_shadow_entry(
    legacy: Stage2Result,
    layered: Stage2Result,
    *,
    caller: str,
    articles: list[dict],
) -> dict[str, Any]:
    """Compute a single caller's shadow comparison entry.

    後で複数 caller 分を 1 ファイルにまとめる際に再利用できるよう、独立関数。
    """
    legacy_top = _top_n_urls_by_final_score(legacy, SHADOW_TOP_N)
    layered_top = _top_n_urls_by_final_score(layered, SHADOW_TOP_N)
    legacy_set = set(legacy_top)
    layered_set = set(layered_top)
    overlap = legacy_set & layered_set
    overlap_ratio = (
        len(overlap) / max(1, min(len(legacy_set), len(layered_set)))
    )
    return {
        "caller": caller,
        "articles_count": len(articles),
        "legacy_top_30": legacy_top,
        "layered_top_30": layered_top,
        "overlap_count": len(overlap),
        "overlap_ratio": round(overlap_ratio, 4),
        "legacy_cost_usd": round(legacy.cost_usd, 6),
        "layered_cost_usd": round(layered.cost_usd, 6),
        "legacy_model": legacy.model,
        "layered_model": layered.model,
        "layer_counts": _count_layers(layered),
        "layered_evaluation_modes": _count_evaluation_modes(layered),
        "legacy_aborted": legacy.aborted,
        "layered_aborted": layered.aborted,
        "_notes": (
            "採用は legacy。layered は shadow（artifact のみ）。"
            "overlap_ratio = 共通 URL 数 / min(両 top set サイズ)。"
        ),
    }


def write_shadow_comparison(
    legacy: Stage2Result,
    layered: Stage2Result,
    *,
    caller: str,
    articles: list[dict],
    path: Path | None = None,
) -> Path:
    """Write or update shadow comparison artifact for the day.

    同日に複数 caller（page1_master / page3 等）が書き込むため、既存ファイルを
    読み込んで該当 caller を上書き or 追加した上で書き戻す。
    """
    p = path or (LOG_DIR / f"stage2_shadow_{_jst_today().isoformat()}.json")
    p.parent.mkdir(parents=True, exist_ok=True)

    existing: dict[str, Any] = {"date": _jst_today().isoformat(), "callers": {}}
    if p.exists():
        try:
            existing = json.loads(p.read_text(encoding="utf-8"))
            if not isinstance(existing, dict):
                existing = {"date": _jst_today().isoformat(), "callers": {}}
            if "callers" not in existing or not isinstance(existing["callers"], dict):
                existing["callers"] = {}
        except (json.JSONDecodeError, OSError):
            # 破損時は新規上書き
            existing = {"date": _jst_today().isoformat(), "callers": {}}

    entry = build_shadow_entry(legacy, layered, caller=caller, articles=articles)
    existing["callers"][caller] = entry

    # tmp + rename for atomicity（C80c markets と同形式）
    import tempfile
    fd = tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8",
        dir=str(p.parent),
        prefix=p.name + ".", suffix=".tmp",
        delete=False,
    )
    tmp_path = fd.name
    try:
        json.dump(existing, fd, ensure_ascii=False, indent=2)
        fd.flush()
        os.fsync(fd.fileno())
        fd.close()
        os.replace(tmp_path, p)
    except Exception:
        fd.close()
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
    return p
