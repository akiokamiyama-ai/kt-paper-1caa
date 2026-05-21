"""第5面 セレンディピティ記事選定（Sprint 4 layout swap で旧 page6 から移動）。

Strategy:
1. 過去 LOOKBACK_DAYS=30 日の displayed_urls_*.json を全 page 横断で読み込み
2. 各記事の URL を sources/*.md と照合し、Source.category に分類
3. category ごとの表示回数をカウント
4. 最も少ない category を「今日の未読領域」として特定（tie はランダム選択）
5. 該当 category の sources/*.md から、過去30日に未表示の記事候補を取得
6. final_score 上位 SELECTION_POOL_SIZE=5 本から random.choice で1本選定
7. logs/page5_history.json に追記

Why "上位 N からランダム抽選"：score 1位固定だと毎日同じ記事になる懸念。
未読領域に出会う「セレンディピティ」を最大化するため、品質の足切りはしつつ
最終選定は乱数で混ぜる。

運用観察 TODO（2026-05-03 culture 導入時の B1 改修に伴う）:
    Sprint 4 で priority="reference" を fetch 対象に追加した（B1 改修）。
    これにより以下の挙動を 30 日運用後に観察し、必要なら B3 昇格を検討する。

    観察ポイント:
    - logs/page5_history.json の category 別表示頻度
    - academic の場合：article_url 集計で SEP/PhilPapers の偏り確認
    - music の場合：Pitchfork/NME の日常化有無
    - 全カテゴリ：Reference ソースが Medium ソースを圧迫していないか

    B3 昇格判断基準:
    - 同じ Reference ソースが 7 日以内に 3 回以上選定された場合、B3 検討
    - カテゴリ内で Reference ソースが Medium を 50% 以上占めるように
      なった場合、Stage 2 評価の priority 重み付け追加を検討

    関連 backlog: Page IV (article_rotator.py) も同じ "high+medium のみ"
    パターン。今 sprint では Page V のみ B1 改修、Page IV は別タスク。
"""

from __future__ import annotations

import html
import json
import random
import re
import sys
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

from ..fetch import run as fetch_run
from ..selector.dedup_filter import (
    filter_recently_displayed,
    load_displayed_urls_log,
)
from ..selector.source_registry import SourceRegistry, build_registry
from ..selector.stage1 import run_stage1
from ..selector.stage2 import run_stage2
from ..selector.stage3 import integrate_scores

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SOURCES_DIR = PROJECT_ROOT / "sources"
LOG_DIR = PROJECT_ROOT / "logs"
HISTORY_PATH = LOG_DIR / "page5_history.json"

LOOKBACK_DAYS: int = 30
SELECTION_POOL_SIZE: int = 5
PER_FETCH_LIMIT: int = 8

# Page V serendipity 対象 category（sources/*.md ファイル名 stem 由来）。
#
# Sprint 6 Phase 2 (2026-05-10) で 8 種 → 5 種に絞った：
#   除外: cooking      (Page VI 専用、URL 持たない設計で count に積まれず常に最少候補)
#   除外: business     (Page I/II/III の本領、重複領域)
#   除外: geopolitics  (Page I/III の本領、重複領域)
#   採用: culture, academic, books, music, outdoor
#
# share/01 の「普段読まない領域」設計思想と整合。companies はそもそも
# page2 専用なので最初から除外。
ELIGIBLE_CATEGORIES: tuple[str, ...] = (
    "academic",
    "books",
    "culture",
    "music",
    "outdoor",
)

# Sprint 6 Phase 2: page5 自身の過去採用カテゴリに penalty を加算して
# 連続採用を構造的に抑制する。
HISTORY_PENALTY_DAYS: int = 7
HISTORY_PENALTY_PER_USE: int = 50  # 他 page の category counts (~30) を上回る重み


_HTML_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")


def _strip_html_simple(text: str | None) -> str:
    if not text:
        return ""
    no_tags = _HTML_TAG_RE.sub(" ", text)
    # 名前付き + 数値文字参照（&#038; &hellip; 等）をまとめてデコード。
    # C19 (2026-05-21): content:encoded 由来のテキストには数値文字参照が
    # 残ることがあり、従来の 5 エンティティ手動置換では取りこぼしていた。
    decoded = html.unescape(no_tags)
    return _WHITESPACE_RE.sub(" ", decoded).strip()


def _get_serendipity_description_text(article: dict) -> str:
    """Serendipity 記事の表示用テキストを返す（C19, 2026-05-21）.

    RSS の ``content:encoded``（長文本文フィールド）があればそれを優先し、
    無ければ ``description`` に fallback。いずれも HTML タグを除去して返す。
    両方とも空なら空文字列。

    Step 1-A 調査（5/21 朝刊観察 C19）で判明した 2 つの実態を 1 関数で吸収：
      * The Trek / SEP / houyhnhnm は description が既に 200 字超
      * AXIS / The Paris Review / The Marginalian は description は短いが
        content:encoded に本文がある
    どちらのソースでも、呼び出し側はこの関数を通すだけで長文を得られる。
    """
    ce = _strip_html_simple(article.get("content_encoded"))
    if ce:
        return ce
    return _strip_html_simple(article.get("description"))


# ---------------------------------------------------------------------------
# History persistence
# ---------------------------------------------------------------------------

def load_history(*, path: Path | None = None) -> dict:
    p = path or HISTORY_PATH
    if not p.exists():
        return {"history": []}
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {"history": []}


def save_history(data: dict, *, path: Path | None = None) -> None:
    p = path or HISTORY_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def append_history_entry(entry: dict, *, path: Path | None = None) -> None:
    h = load_history(path=path)
    h.setdefault("history", []).append(entry)
    save_history(h, path=path)


def update_history_column_fields(
    *,
    target_date: date,
    article_url: str,
    ai_kamiyama_called: bool,
    ai_kamiyama_failed: bool,
    fallback_used: bool,
    history_path: Path | None = None,
    ai_kamiyama_url: str | None = None,
    ai_kamiyama_title: str | None = None,
    ai_kamiyama_category: str | None = None,
    ai_kamiyama_source_name: str | None = None,
) -> bool:
    """Update the most recent matching history entry with column-gen status.

    selector が select_for_today で history に書く時点では column 生成が
    まだ走っていないため、3 つのステータスフィールドは placeholder の False で
    記録される。caller (build_page_five_v2) が column 生成後に本関数を呼んで
    実際のステータス値で上書きする設計（責務分離：history I/O は selector 内に
    閉じ込める、caller は column status を渡すのみ）。

    Sprint 5 task #5 (2026-05-04 修正): 過去の history (5/2, 5/3 の 6 entries) は
    bug 期間データとして false のまま放置。本修正以降のデータから有効。

    Sprint 7 Phase 1 Step 2 (2026-05-19): AIかみやま が serendipity 記事から
    独立した記事に論評する構造に変更。AIかみやま が言及した記事のメタ情報
    （url / title / category / source_name）を ai_kamiyama_* フィールドとして
    同じ entry に追加。article_url は引き続き serendipity 記事の URL
    (後方互換、_apply_history_penalty 等の既存ロジックは無修正)。

    Parameters
    ----------
    target_date :
        対象記事が表示された日（history entry の displayed_on に一致）
    article_url :
        serendipity 記事の URL（history entry の article_url に一致、matching key）
    ai_kamiyama_called :
        column 生成 API が呼ばれたか
    ai_kamiyama_failed :
        column 生成が失敗したか（API 接続失敗 / 空応答）
    fallback_used :
        fallback テキストが使われたか
    history_path :
        テスト用に history JSON のパスを上書き可能。None で本番 HISTORY_PATH
    ai_kamiyama_url / ai_kamiyama_title / ai_kamiyama_category /
    ai_kamiyama_source_name :
        Sprint 7 Phase 1 Step 2 追加。AIかみやま が論評した記事のメタ。
        None の場合は entry に書き込まない（既存呼び出しの後方互換）。

    Returns
    -------
    bool
        True if an entry was updated, False otherwise. False の場合は
        stderr に warning を出力するが、caller の処理は継続される
        （紙面生成本体への影響なし、ログの不整合のみ残る）。
    """
    h = load_history(path=history_path)
    entries = h.get("history") or []
    target_iso = target_date.isoformat()
    # 同じ (displayed_on, article_url) が複数あれば「最新（末尾）」を更新する。
    matched_idx = -1
    for i, entry in enumerate(entries):
        if (
            entry.get("displayed_on") == target_iso
            and entry.get("article_url") == article_url
        ):
            matched_idx = i  # keep the latest (last) match
    if matched_idx < 0:
        print(
            f"[page5] history update: entry not found for "
            f"{article_url!r} on {target_iso}",
            file=sys.stderr,
        )
        return False
    entries[matched_idx]["ai_kamiyama_called"] = ai_kamiyama_called
    entries[matched_idx]["ai_kamiyama_failed"] = ai_kamiyama_failed
    entries[matched_idx]["fallback_used"] = fallback_used
    # Sprint 7 Phase 1 Step 2: AIかみやま 記事メタ（None なら書込み skip）
    if ai_kamiyama_url is not None:
        entries[matched_idx]["ai_kamiyama_url"] = ai_kamiyama_url
    if ai_kamiyama_title is not None:
        entries[matched_idx]["ai_kamiyama_title"] = ai_kamiyama_title
    if ai_kamiyama_category is not None:
        entries[matched_idx]["ai_kamiyama_category"] = ai_kamiyama_category
    if ai_kamiyama_source_name is not None:
        entries[matched_idx]["ai_kamiyama_source_name"] = ai_kamiyama_source_name
    h["history"] = entries
    save_history(h, path=history_path)
    return True


# ---------------------------------------------------------------------------
# Step 1〜2: walk past 30 days' displayed_urls_*.json across all pages
# ---------------------------------------------------------------------------

def _collect_displayed_urls_with_categories(
    *,
    today: date,
    days: int = LOOKBACK_DAYS,
    registry: SourceRegistry | None = None,
) -> tuple[set[str], Counter]:
    """Walk past ``days`` of displayed_urls logs across page1〜page6.

    Returns ``(displayed_urls, category_counts)``:
    * ``displayed_urls`` — set of every URL displayed across all pages,
      used by the caller for dedup filtering.
    * ``category_counts`` — count per ``ELIGIBLE_CATEGORIES`` of how many
      times that category was displayed in the window. Used to find the
      "least-shown" category for today's serendipity pick.
    """
    if registry is None:
        registry = build_registry(SOURCES_DIR)

    name_to_category: dict[str, str] = {
        name: src.category for name, src in registry.sources_by_name.items()
    }

    def category_for_url(url: str) -> str | None:
        """Best-effort category lookup by URL host matching against registry."""
        # First-pass strategy: check if any source URL is a substring prefix.
        # SourceRegistry has by_host but expects URLs from articles (not sources).
        # Simpler: brute-force try each source's URL host.
        from urllib.parse import urlparse
        try:
            host = (urlparse(url).hostname or "").removeprefix("www.")
        except Exception:
            return None
        if not host:
            return None
        for src_name, src in registry.sources_by_name.items():
            try:
                src_host = (urlparse(src.url).hostname or "").removeprefix("www.")
            except Exception:
                continue
            if src_host and (src_host == host or host.endswith("." + src_host)):
                # source.category may be e.g. "companies:Cocolomi" — for page6
                # purposes we collapse to base category (the bit before ':').
                return src.category.split(":", 1)[0]
        return None

    displayed_urls: set[str] = set()
    category_counts: Counter = Counter()
    # Walk [today - days, today - 1] inclusive. Today's own selection is
    # NOT yet recorded, so excluding it is automatic.
    for i in range(1, days + 1):
        d = today - timedelta(days=i)
        log = load_displayed_urls_log(d)
        if log is None:
            continue

        # page1
        for u in log.get("page1_urls", []) or []:
            if u:
                displayed_urls.add(u)
                cat = category_for_url(u)
                if cat in ELIGIBLE_CATEGORIES:
                    category_counts[cat] += 1
        # page2 (per-company dict — companies category excluded from
        # ELIGIBLE_CATEGORIES anyway, but we still collect URL for dedup)
        for u in (log.get("page2_urls", {}) or {}).values():
            if u:
                displayed_urls.add(u)
        # page3 (固定長6)
        for u in log.get("page3_urls", []) or []:
            if u:
                displayed_urls.add(u)
                cat = category_for_url(u)
                if cat in ELIGIBLE_CATEGORIES:
                    category_counts[cat] += 1
        # page4
        for u in log.get("page4_urls", []) or []:
            if u:
                displayed_urls.add(u)
                cat = category_for_url(u)
                if cat in ELIGIBLE_CATEGORIES:
                    category_counts[cat] += 1
        # page5 (single URL or null — Sprint 4 layout swap, was page6_url)
        u = log.get("page5_url")
        if u:
            displayed_urls.add(u)
            cat = category_for_url(u)
            if cat in ELIGIBLE_CATEGORIES:
                category_counts[cat] += 1
        # page6 (per-area dict — Sprint 4 layout swap, was page5_urls)
        for u in (log.get("page6_urls", {}) or {}).values():
            if u:
                displayed_urls.add(u)
                cat = category_for_url(u)
                if cat in ELIGIBLE_CATEGORIES:
                    category_counts[cat] += 1

    return displayed_urls, category_counts


# ---------------------------------------------------------------------------
# Step 3〜4: identify least-shown category (with random tie-break)
# ---------------------------------------------------------------------------

def _apply_history_penalty(
    counts: Counter,
    history: list[dict],
    today: date,
    *,
    days_back: int = HISTORY_PENALTY_DAYS,
    penalty_per_use: int = HISTORY_PENALTY_PER_USE,
) -> Counter:
    """page5 自身の過去採用カテゴリに penalty を加算したカウントを返す.

    Sprint 6 Phase 2 (2026-05-10) 追加。``_collect_displayed_urls_with_categories``
    が返す全 page 横断の counts では、business / geopolitics / academic / books が
    他面で頻繁に表示されるため count が高い → 低 count の category（特に
    culture）が serendipity で連続採用される偏りが発生（5/4-5/10 観察）。

    page5 自身の history から過去 ``days_back`` 日に採用された category を
    抽出し、count に ``penalty_per_use`` × 採用回数を加算することで、
    最少候補から押し出す。``penalty_per_use=50`` は他 page の典型的な
    category count (~30) を上回るよう設定。

    今日 (``today``) の採用は history にまだ無いので除外される。
    ``cutoff = today - days_back``、対象期間は ``[cutoff, today)``。
    """
    penalized = Counter(counts)
    cutoff = today - timedelta(days=days_back)
    for entry in history:
        try:
            d = date.fromisoformat(entry.get("displayed_on", ""))
        except (ValueError, TypeError):
            continue
        if d < cutoff or d >= today:
            continue
        cat = entry.get("article_category")
        if cat:
            penalized[cat] += penalty_per_use
    return penalized


def _least_shown_categories(
    counts: Counter,
    *,
    eligible: tuple[str, ...] = ELIGIBLE_CATEGORIES,
) -> list[str]:
    """Return the list of categories tied for the lowest count.

    A category not present in ``counts`` is treated as count=0. If multiple
    categories share the minimum, all of them are returned for the caller
    to randomly pick from.
    """
    counts_full = {c: counts.get(c, 0) for c in eligible}
    min_count = min(counts_full.values())
    return [c for c, n in counts_full.items() if n == min_count]


def pick_target_category(
    counts: Counter,
    *,
    rng: random.Random | None = None,
    eligible: tuple[str, ...] = ELIGIBLE_CATEGORIES,
) -> tuple[str, list[str]]:
    """Pick today's serendipity category.

    Returns ``(chosen_category, tie_candidates)``. ``tie_candidates`` is the
    full list of categories at the minimum count (informational — for
    logging). If only one category is at the minimum, ``tie_candidates``
    has length 1.
    """
    if rng is None:
        rng = random.Random()
    candidates = _least_shown_categories(counts, eligible=eligible)
    return rng.choice(candidates), candidates


# ---------------------------------------------------------------------------
# Step 5〜6: fetch + Stage 1+2+3 + dedup + pool selection
# ---------------------------------------------------------------------------

def _fetch_and_score_category(
    category: str,
    *,
    pre_evaluated: dict[str, dict] | None = None,
    registry: SourceRegistry | None = None,
) -> tuple[list[dict], float]:
    """Fetch ``{category}.md`` High+Medium+Reference, run Stage 1+2+3.

    Reference 配置のソースもセレンディピティ候補として fetch する（B1 改修、
    2026-05-03）。priority による重み付けは行わず、Stage 2 LLM 評価による
    品質フィルタに委譲する。観察 TODO はモジュール docstring 参照。
    """
    if registry is None:
        registry = build_registry(SOURCES_DIR)

    raw = []
    for pri in ("high", "medium", "reference"):
        try:
            summary = fetch_run(
                category=category, priority=pri, limit=PER_FETCH_LIMIT,
                no_dedupe=True, write_log=False,
            )
            raw.extend(summary.get("articles", []))
        except Exception as e:
            print(
                f"[page6] fetch_run({category}, {pri}) failed: "
                f"{type(e).__name__}: {e}",
                file=sys.stderr,
            )

    seen: set[str] = set()
    pipeline_dicts: list[dict] = []
    for a in raw:
        url = a.link or ""
        if not url or url in seen:
            continue
        seen.add(url)
        body = "\n".join(a.body_paragraphs) if a.body_paragraphs else ""
        pipeline_dicts.append({
            "url": url,
            "title": a.title,
            "description": _strip_html_simple(a.description),
            # content_encoded は生 HTML のまま保持（C19, 2026-05-21）。
            # 表示時に _get_serendipity_description_text が strip して使う。
            "content_encoded": a.content_encoded,
            "body": _strip_html_simple(body),
            "source_name": a.source_name,
            "source_url": None,
            "pub_date": a.pub_date.isoformat() if a.pub_date else None,
        })

    s1_out = run_stage1(pipeline_dicts)
    surviving = [x for x in s1_out if not x.get("is_excluded")]
    if not surviving:
        return [], 0.0

    cached: list[dict] = []
    uncached: list[dict] = []
    for art in surviving:
        url = art.get("url")
        if url and pre_evaluated and url in pre_evaluated:
            merged = dict(art)
            merged.update(pre_evaluated[url])
            cached.append(merged)
        else:
            uncached.append(art)

    cost = 0.0
    if uncached:
        s2 = run_stage2(uncached)
        cost += s2.cost_usd
        integrate_scores(s2.evaluations_by_url)
        by_url = s2.evaluations_by_url
        for art in uncached:
            url = art.get("url")
            if url and url in by_url:
                art.update(by_url[url])
                cached.append(art)

    for art in cached:
        if not art.get("category"):
            name = art.get("source_name")
            if name:
                src = registry.sources_by_name.get(name)
                if src:
                    art["category"] = src.category

    return cached, cost


def select_from_pool(
    candidates: list[dict],
    *,
    pool_size: int = SELECTION_POOL_SIZE,
    rng: random.Random | None = None,
) -> dict | None:
    """Pick from top-``pool_size`` by final_score using random.choice.

    Returns None if ``candidates`` is empty.
    """
    if not candidates:
        return None
    if rng is None:
        rng = random.Random()
    sorted_candidates = sorted(
        candidates, key=lambda a: a.get("final_score", 0.0), reverse=True,
    )
    pool = sorted_candidates[:pool_size]
    return rng.choice(pool)


# ---------------------------------------------------------------------------
# Public entry
# ---------------------------------------------------------------------------

def select_for_today(
    target_date: date | None = None,
    *,
    pre_evaluated: dict[str, dict] | None = None,
    rng: random.Random | None = None,
    persist: bool = True,
    history_path: Path | None = None,
    registry: SourceRegistry | None = None,
) -> dict:
    """Run the full Page VI selector. Returns a dict for the renderer.

    Returns::

        {
            "article": {url, title, source_name, pub_date, description, ...} | None,
            "category": str | None,
            "tie_candidates": list[str],
            "selected_from_pool_size": int,
            "is_placeholder": bool,
            "cost_usd": float,
        }
    """
    if target_date is None:
        target_date = date.today()
    if rng is None:
        rng = random.Random()
    if registry is None:
        registry = build_registry(SOURCES_DIR)

    # Step 1〜2: walk history → counts + displayed urls set
    displayed_urls, counts = _collect_displayed_urls_with_categories(
        today=target_date, registry=registry,
    )

    # Sprint 6 Phase 2: page5 自身の過去採用 category に penalty 加算
    # （連続採用を構造的に抑制）
    page5_history = load_history(path=history_path).get("history", [])
    counts = _apply_history_penalty(counts, page5_history, target_date)

    # Step 3〜4: pick target category (with tie randomization)
    chosen_cat, tie_candidates = pick_target_category(counts, rng=rng)

    # Step 5: fetch + score for that category
    scored, cost = _fetch_and_score_category(
        chosen_cat, pre_evaluated=pre_evaluated, registry=registry,
    )
    if scored:
        # Dedup against past 30-day displayed URLs (any page)
        before = len(scored)
        scored = filter_recently_displayed(scored, displayed_urls)
        removed = before - len(scored)
        if removed:
            print(
                f"[page6] dedup: removed {removed}/{before} already-shown "
                f"({len(scored)} remain in {chosen_cat})",
                file=sys.stderr,
            )

    if not scored:
        # Placeholder path
        if persist:
            append_history_entry({
                "displayed_on": target_date.isoformat(),
                "article_url": None,
                "article_title": None,
                "article_category": chosen_cat,
                "tie_candidates": tie_candidates,
                "selected_from_pool_size": 0,
                "ai_kamiyama_called": False,
                "ai_kamiyama_failed": False,
                "fallback_used": False,
                "is_placeholder": True,
            }, path=history_path)
        return {
            "article": None,
            "category": chosen_cat,
            "tie_candidates": tie_candidates,
            "selected_from_pool_size": 0,
            "is_placeholder": True,
            "cost_usd": cost,
        }

    # Step 6: top-N pool → random.choice
    article = select_from_pool(scored, rng=rng)
    pool_size = min(SELECTION_POOL_SIZE, len(scored))

    # Persist (ai_kamiyama_called/failed/fallback are filled by caller after column gen)
    # Here we just record the article selection itself; the caller will
    # update the entry after column generation runs.
    if persist:
        append_history_entry({
            "displayed_on": target_date.isoformat(),
            "article_url": article.get("url"),
            "article_title": article.get("title"),
            "article_category": chosen_cat,
            "tie_candidates": tie_candidates,
            "selected_from_pool_size": pool_size,
            # placeholders for column-gen status — caller may overwrite
            "ai_kamiyama_called": False,
            "ai_kamiyama_failed": False,
            "fallback_used": False,
            "is_placeholder": False,
        }, path=history_path)

    return {
        "article": article,
        "category": chosen_cat,
        "tie_candidates": tie_candidates,
        "selected_from_pool_size": pool_size,
        "is_placeholder": False,
        "cost_usd": cost,
    }
