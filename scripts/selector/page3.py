"""Page 3 (中面 General News) selection pipeline.

Implements ``docs/page3_design_v1.md`` v1.0 — 6領域 × 各1本の領域配分。

Pipeline (per ``docs/page3_design_v1.md`` §4):

* business.md / geopolitics.md / academic.md / books.md の High+Medium を
  領域横断的に取得（``default_fetcher``）。
* Stage 1（機械フィルタ）→ Stage 2（美意識 LLM）→ Stage 3（final_score 統合）。
  Stage 2 結果は ``pre_evaluated`` キャッシュ経由で第1面と共有可能。
* dedup：当日の page1/page2 で選定された URL を除外、過去 N=7 日に
  page3 で表示された URL を除外。
* 領域振分け（``_region_for``、判定順序 R6→R5→R3→R2→R4→R1）。
* 各領域内で final_score 上位1本を選定。候補なし領域は ``None``。
* kicker はルールベース（``_generate_kicker``）。LLM 解説は付けない。

Public entry points
-------------------
* ``run_page3_pipeline(scored_or_fetcher, ...)`` — メインのオーケストレーション
* ``select_page3_articles(scored, ...)`` — 領域振分け + 選定（in-memory）
* ``_region_for(article)`` — 領域判定（テスト用）
* ``_generate_kicker(article, region)`` — kicker 生成（テスト用）
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable

from ..lib import llm_usage
from .source_registry import SourceRegistry, build_registry
from .stage1 import run_stage1
from .stage2 import run_stage2
from .stage3 import integrate_scores

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SOURCES_DIR = PROJECT_ROOT / "sources"
LOG_DIR = PROJECT_ROOT / "logs"

# 紙面表示順（R1→R6）。1行目=R1/R2/R3、2行目=R4/R5/R6（CSS Grid 3列）。
REGIONS: tuple[str, ...] = ("R1", "R2", "R3", "R4", "R5", "R6")

# 判定順序（specific → broad）。docs/page3_design_v1.md §3.3。
# 一記事は最初にマッチした領域に振り分ける（重複振分けはしない）。
REGION_DETECTION_ORDER: tuple[str, ...] = ("R6", "R5", "R3", "R2", "R4", "R1")

# 紙面表示用の領域名。placeholder の kicker fallback でも使う。
REGION_DISPLAY_NAMES: dict[str, str] = {
    "R1": "国際金融・地政経済",
    "R2": "国内マクロ・産業",
    "R3": "国際規制・テクノ覇権",
    "R4": "国内産業・経営",
    "R5": "文化・書評・社会",
    "R6": "学術・科学",
}

# kicker fallback：source_name map / title 抽出に失敗した時の最終手段。
# 紙面の kicker としては短く保ちたいので、領域名の短縮形を使う。
REGION_KICKER_FALLBACK: dict[str, str] = {
    "R1": "国際金融",
    "R2": "国内マクロ",
    "R3": "国際規制",
    "R4": "国内産業",
    "R5": "文化・社会",
    "R6": "学術・科学",
}

# source_name → デフォルト kicker map（v1、25 ソース）。
# title 抽出が失敗した時の第2候補。docs/page3_design_v1.md §13 Q1 確定済。
KICKER_BY_SOURCE: dict[str, str] = {
    "The Economist":                       "London",
    "BBC Business":                        "London・産業",
    "Reuters Business":                    "London・市場",
    "Reuters World":                       "London・市場",
    "Foreign Affairs":                     "Washington",
    "Foreign Policy":                      "Washington・国際",
    "Project Syndicate":                   "国際・論考",  # 神山さん指定（寄稿者世界中、Pragueは混乱招くため）
    "Brookings Institution":               "Washington・政策",
    "CSIS":                                "Washington・戦略",
    "RAND Corporation":                    "Santa Monica・戦略",
    "War on the Rocks":                    "Washington・安全保障",
    "Foresight":                           "東京・国際",
    "日本経済新聞":                          "東京・経済",
    "東洋経済オンライン":                     "東京・産業",
    "ITmedia ビジネスオンライン":             "東京・経営",
    "McKinsey Insights":                   "New York・経営",
    "Bloomberg Opinion":                   "New York・市場",
    "Behavioral Scientist":                "New York・行動経済学",
    "NBER Working Papers":                 "Cambridge・経済学",
    "Aeon":                                "London・思想",
    "Philosophy Now":                      "London・哲学",
    "Stanford Encyclopedia of Philosophy": "Stanford・哲学",
    "The Marginalian":                     "Boston・人文",
    "集英社新書プラス":                       "東京・新書",
    "春秋社":                               "東京・思想",
    "青土社":                               "東京・現代思想",
    "東京大学 公共政策大学院":                  "東京・公共政策",
    "DIAMONDハーバード・ビジネス・レビュー":    "Boston・経営",
    "HBR":                                 "Boston・経営",
    "Quanta Magazine":                     "New York・科学",
    "Nautilus":                            "New York・科学",
    "日経サイエンス":                         "東京・科学",
}

# Title 内の地名抽出 whitelist（先頭5単語以内のみマッチ）。
# 厳密マッチで誤判定を避ける。docs/page3_design_v1.md §8.3。
TITLE_LOCATION_WHITELIST: tuple[str, ...] = (
    # 英文
    "Tokyo", "Beijing", "Shanghai", "Seoul", "Hong Kong", "Taipei",
    "Washington", "Brussels", "London", "Paris", "Berlin", "Frankfurt",
    "Geneva", "New York", "Boston", "Singapore", "Mumbai", "New Delhi",
    "Sydney", "Tel Aviv", "Cairo", "Dubai", "Moscow", "Kiev", "Kyiv",
    "Madrid", "Rome", "Milan", "Helsinki", "Stockholm",
    # 和文
    "東京", "大阪", "京都", "横浜", "名古屋", "札幌", "福岡",
    "北京", "上海", "香港", "ソウル", "ワシントン", "ブリュッセル",
    "ロンドン", "パリ", "ベルリン", "ローマ", "シンガポール",
    "モスクワ", "テルアビブ", "ドバイ",
)

# 日本語ソース判定（_is_japanese_source 簡易版、translate と同じ思想）。
JAPANESE_SOURCE_PATTERNS: tuple[str, ...] = (
    "Foresight", "Forbes Japan", "ZDNet Japan", "ITmedia",
    "PR TIMES", "東洋経済", "DIAMOND", "日本経済新聞", "日経",
    "新書", "春秋社", "青土社", "集英社", "ロイター", "プロジェクト",
    "東京大学",
)

# 日本マクロ・産業の主要ソース（R2 / R4 判定で使用）。
JAPAN_PRIMARY_SOURCES: tuple[str, ...] = (
    "日本経済新聞", "東洋経済オンライン",
)

# books.md「自然科学ノンフィクション」セクションのソース。R6 に振り分ける。
# books.md L110-153 で確認済。それ以外の books.md ソース（小説・純文学・SF）
# は R5（文化）に振り分ける。
BOOKS_NATURAL_SCIENCE_SOURCES: tuple[str, ...] = (
    "Quanta Magazine", "Nautilus", "日経サイエンス", "The Marginalian",
)

# 領域別キーワード集合。docs/page3_design_v1.md §5 を逐語転記。
# v1.0 の出発点。1〜2 週間運用してログを見て v1.1 で調整。

R1_KEYWORDS: tuple[str, ...] = (
    # 通貨・市場
    "為替", "円安", "円高", "通貨", "ドル", "ユーロ", "利下げ", "利上げ",
    "中央銀行", "FRB", "Fed", "ECB", "BoJ", "sovereign", "currency",
    # 地政経済
    "地経学", "経済安全保障", "サプライチェーン", "supply chain",
    "decoupling", "制裁", "sanctions", "BRICS", "OPEC",
    # 国家間機関
    "G7", "G20", "IMF", "WTO", "World Bank", "OECD",
)

R2_KEYWORDS: tuple[str, ...] = (
    # 人口
    "人口", "生産年齢", "出生", "高齢化", "労働力不足",
    # 産業政策
    "経産省", "METI", "産業政策", "補助金", "スタートアップ支援", "産業競争力",
    # マクロ指標
    "GDP", "物価", "インフレ", "デフレ", "賃上げ", "春闘", "日銀", "日本銀行",
)

R3_KEYWORDS: tuple[str, ...] = (
    # AI 規制
    "AI Act", "AI規制", "AI法", "Bletchley", "Hiroshima Process",
    "AI Safety", "AI Bill", "生成AI規制", "AI事業者ガイドライン",
    # 半導体地政
    "半導体", "semiconductor", "chip ban", "CHIPS Act", "EUV",
    "ファウンドリ", "foundry", "TSMC", "ASML",
    # データ・プラットフォーム規制
    "GDPR", "DSA", "DMA", "Section 230", "データ規制", "個人情報保護",
    "antitrust", "反トラスト", "独禁法",
    # テクノ覇権
    "techno-democracy", "techno-authoritarian", "decoupling tech",
    "Huawei", "5G ban", "export control",
)

R4_KEYWORDS: tuple[str, ...] = (
    # 企業戦略
    "M&A", "事業再編", "経営戦略", "企業統治", "ガバナンス",
    "ESG", "サステナビリティ",
    # 業界再編
    "業界再編", "統合", "買収", "提携", "合弁",
    # 組織論
    "組織開発", "人的資本", "リスキリング", "ジョブ型", "メンバーシップ型",
    # 日本企業固有
    "トヨタ", "ソニー", "日立", "三菱", "三井", "住友", "商社", "財閥",
    "ファミリービジネス",
)

R5_KEYWORDS: tuple[str, ...] = (
    # 書評・出版
    "書評", "新刊", "翻訳", "受賞", "文学賞", "芥川賞", "直木賞",
    "ノーベル文学賞", "Booker", "Pulitzer",
    # 文化動向
    "美術館", "展覧会", "exhibition", "retrospective", "biennale",
    "ドキュメンタリー",
    # 社会論
    "格差", "inequality", "デモクラシー", "populism", "移民",
    "人口減少社会論",
    # 哲学エッセイ
    "essay", "エッセイ", "随筆", "現代思想", "倫理",
)

R6_KEYWORDS: tuple[str, ...] = (
    # 自然科学
    "物理学", "physics", "量子", "quantum", "宇宙", "進化", "evolution",
    "ゲノム", "neuroscience", "神経科学",
    # 認知・心理
    "認知科学", "cognitive", "行動経済学", "behavioral",
    "意思決定", "decision-making",
    # 哲学・人文学
    "哲学", "philosophy", "ethics", "phenomenology", "存在論",
    # 学術機関
    "working paper", "peer review", "NBER",
)

# Page III dedup window。docs/page3_design_v1.md §6.1。
PAGE3_DEDUP_DAYS: int = 7

# Stage 2 batch のサイズ。stage2.py default に揃える。
PER_FETCH_LIMIT: int = 8


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class RegionSelection:
    region: str
    article: dict | None
    final_score: float | None
    fallback_reason: str | None  # "no_candidates" / "all_deduped" / etc.


@dataclass
class Page3Result:
    selections: dict[str, RegionSelection] = field(default_factory=dict)
    cost_usd: float = 0.0
    today: date | None = None
    placeholder_count: int = 0
    candidates_total: int = 0
    candidates_after_dedup: int = 0


# ---------------------------------------------------------------------------
# Module-level cache
# ---------------------------------------------------------------------------

_REGISTRY: SourceRegistry | None = None


def _get_registry() -> SourceRegistry:
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = build_registry(SOURCES_DIR)
    return _REGISTRY


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )


def _is_japanese_source(source_name: str | None) -> bool:
    """簡易判定：source_name 内に JA pattern を含む or 2 文字以上の和文を含む。

    ``regen_front_page_v2._is_japanese_source`` と同じロジック（独立実装で
    依存を避ける）。
    """
    if not source_name:
        return False
    if any(pat in source_name for pat in JAPANESE_SOURCE_PATTERNS):
        return True
    name_stripped = re.sub(r"[（(][^）)]*[）)]", "", source_name)
    ja_chars = sum(
        1 for c in name_stripped
        if "぀" <= c <= "ゟ" or "゠" <= c <= "ヿ" or "一" <= c <= "鿿"
    )
    return ja_chars >= 2


def _has_keyword(text: str, keywords: tuple[str, ...]) -> bool:
    """case-insensitive substring match. 和文キーワードはそのまま contains 判定。"""
    if not text:
        return False
    lower = text.lower()
    for kw in keywords:
        if kw.lower() in lower:
            return True
    return False


def _haystack(article: dict) -> str:
    """title + description を連結した検索対象テキスト。"""
    return " ".join((article.get("title") or "", article.get("description") or ""))


def _category_of(article: dict) -> str:
    """article["category"] が無ければ registry から引いて埋める。"""
    cat = article.get("category")
    if cat:
        return cat
    name = article.get("source_name")
    if name:
        src = _get_registry().sources_by_name.get(name)
        if src:
            article["category"] = src.category
            return src.category
    return ""


def _source_name_match(article: dict, candidates: tuple[str, ...]) -> bool:
    """source_name の前方/部分一致で candidates のいずれかにヒットすれば True."""
    name = article.get("source_name") or ""
    return any(c in name for c in candidates)


# ---------------------------------------------------------------------------
# Region detection (judgment order: R6 → R5 → R3 → R2 → R4 → R1)
# ---------------------------------------------------------------------------

def _matches_R6(article: dict) -> bool:
    """学術・科学：academic.md / The Economist Science / 自然科学ノンフ / R6 keywords."""
    cat = _category_of(article)
    name = article.get("source_name") or ""

    # academic.md は基本 R6（ただし R5 keyword が強くマッチすれば後で R5 が優先される
    # —— DETECTION_ORDER で R6 を先に判定するので、R6 keyword が無ければ次に進む）
    if cat == "academic":
        # academic.md の Aeon / The Marginalian は人文寄りなので、R5 キーワードと
        # 競合する場合は R6 で取らずに次に流す（_matches_R5 で拾う）。
        if _source_name_match(article, ("Aeon", "The Marginalian")):
            return _has_keyword(_haystack(article), R6_KEYWORDS)
        return True

    # books.md の自然科学ノンフィクションセクション
    if cat == "books" and _source_name_match(article, BOOKS_NATURAL_SCIENCE_SOURCES):
        return True

    # The Economist Science and Technology
    if "The Economist" in name:
        url = article.get("url") or ""
        if "/science-and-technology/" in url:
            return True

    # キーワード一致
    return _has_keyword(_haystack(article), R6_KEYWORDS)


def _matches_R5(article: dict) -> bool:
    """文化・書評・社会：books.md（自然科学ノンフ以外）/ Aeon / The Marginalian / R5 keywords."""
    cat = _category_of(article)

    # books.md は基本 R5（自然科学ノンフは _matches_R6 で先に拾われる）
    if cat == "books":
        return True

    # academic.md の Aeon / The Marginalian で R6 を取れなかったケース
    if cat == "academic" and _source_name_match(article, ("Aeon", "The Marginalian")):
        return True

    # キーワード一致
    return _has_keyword(_haystack(article), R5_KEYWORDS)


def _matches_R3(article: dict) -> bool:
    """国際規制・テクノ覇権：R3 keywords。ソース判定はキーワードに包含。"""
    return _has_keyword(_haystack(article), R3_KEYWORDS)


def _matches_R2(article: dict) -> bool:
    """国内マクロ・産業：日本主要ソース or R2 keywords + 日本文脈。"""
    cat = _category_of(article)

    # business.md の日本主要ソース：マクロ・人口・産業政策キーワードを含む
    if cat == "business" and _source_name_match(article, JAPAN_PRIMARY_SOURCES):
        if _has_keyword(_haystack(article), R2_KEYWORDS):
            return True
        # 日本主要ソースで R4 keyword も無いなら R2 にデフォルト振分け
        # （企業個別記事は R4 で先に拾う、ここまで降りてきたものはマクロ寄りと推定）
        if not _has_keyword(_haystack(article), R4_KEYWORDS):
            return True

    # キーワード一致（"日本" or "国内" を含む文脈）
    if _has_keyword(_haystack(article), R2_KEYWORDS):
        haystack = _haystack(article)
        if "日本" in haystack or "国内" in haystack or _is_japanese_source(article.get("source_name")):
            return True

    return False


def _matches_R4(article: dict) -> bool:
    """国内産業・経営：日本/Boston系経営ソース or R4 keywords."""
    cat = _category_of(article)

    if cat != "business":
        # business.md 以外でも、企業戦略キーワードが強くマッチすれば R4 に取る
        if _has_keyword(_haystack(article), R4_KEYWORDS):
            return True
        return False

    # business.md の経営論考ソース
    business_management_sources = (
        "東洋経済オンライン", "ITmedia ビジネスオンライン",
        "DIAMONDハーバード・ビジネス・レビュー", "HBR",
        "McKinsey Insights", "BCG", "Strategy+Business",
    )
    if _source_name_match(article, business_management_sources):
        return True

    # キーワード一致
    return _has_keyword(_haystack(article), R4_KEYWORDS)


def _matches_R1(article: dict) -> bool:
    """国際金融・地政経済：geopolitics.md 全般 / business.md 国際 / R1 keywords."""
    cat = _category_of(article)
    name = article.get("source_name") or ""

    # geopolitics.md は基本 R1（R6/R5/R3/R2/R4 で拾われなかったもの）
    if cat == "geopolitics":
        return True

    # business.md の国際論考ソース
    international_business_sources = (
        "The Economist", "Reuters Business", "Foreign Affairs",
        "Foresight", "Bloomberg Opinion",
    )
    if cat == "business" and any(s in name for s in international_business_sources):
        return True

    # キーワード一致
    return _has_keyword(_haystack(article), R1_KEYWORDS)


_REGION_MATCHERS: dict[str, Callable[[dict], bool]] = {
    "R1": _matches_R1,
    "R2": _matches_R2,
    "R3": _matches_R3,
    "R4": _matches_R4,
    "R5": _matches_R5,
    "R6": _matches_R6,
}


def _region_for(article: dict) -> str | None:
    """記事を1領域に振分け。docs/page3_design_v1.md §3.3。

    判定順序 R6 → R5 → R3 → R2 → R4 → R1。最初にマッチした領域に
    振り分ける。どれにもマッチしなければ None（第3面の対象外）。
    """
    for region in REGION_DETECTION_ORDER:
        matcher = _REGION_MATCHERS[region]
        if matcher(article):
            return region
    return None


def _filter_for_region(articles: list[dict], region: str) -> list[dict]:
    """articles を全件走査して、その記事が region に振分けられるものだけ返す。

    DETECTION_ORDER 通りの一意振分けを使うので、同じ記事が複数領域に
    含まれることはない（_region_for が他領域を返した記事は除外）。
    """
    out: list[dict] = []
    for art in articles:
        if _region_for(art) == region:
            out.append(art)
    return out


def _select_top_for_region(articles: list[dict], region: str) -> dict | None:
    """指定 region 内で final_score 上位1本を選ぶ。候補なしは None.

    threshold は適用しない（docs/page3_design_v1.md §13 Q2 で「候補があれば
    最上位を選ぶ」確定）。
    """
    candidates = _filter_for_region(articles, region)
    if not candidates:
        return None
    candidates.sort(key=lambda a: a.get("final_score", 0.0), reverse=True)
    return candidates[0]


# ---------------------------------------------------------------------------
# Kicker generation (rule-based)
# ---------------------------------------------------------------------------

def _extract_title_location(title: str | None) -> str | None:
    """先頭5単語以内に whitelist 地名があれば返す。

    英文：単語境界で split、和文：substring 検索（whitelist が短いので衝突
    リスクは低い）。docs/page3_design_v1.md §8.3。
    """
    if not title:
        return None
    title = title.strip()
    # 先頭5単語（空白区切り）に限定して走査
    head = " ".join(title.split()[:5])
    # 和文も英文も先頭5単語ぶん（和文は単語の概念が薄いので、先頭40字相当を見る）
    head_ja = title[:40]
    for loc in TITLE_LOCATION_WHITELIST:
        # ASCII 始まりの英地名は単語境界マッチ、それ以外は単純 contains
        if loc[0].isascii():
            # 単語境界（前後がアルファベット数字以外）でマッチ
            pat = re.compile(rf"(?<![A-Za-z0-9]){re.escape(loc)}(?![A-Za-z0-9])")
            if pat.search(head):
                return loc
        else:
            if loc in head_ja:
                return loc
    return None


def _generate_kicker(article: dict, region: str) -> str:
    """記事の kicker を3段階で生成。

    1. Title 内 whitelist 地名抽出
    2. source_name → KICKER_BY_SOURCE map
    3. REGION_KICKER_FALLBACK[region]
    """
    # 1) Title 抽出
    loc = _extract_title_location(article.get("title"))
    if loc:
        return loc

    # 2) source_name map
    source_name = article.get("source_name") or ""
    for src_pat, kicker in KICKER_BY_SOURCE.items():
        if src_pat in source_name:
            return kicker

    # 3) Fallback
    return REGION_KICKER_FALLBACK.get(region, "海外")


# ---------------------------------------------------------------------------
# Selection
# ---------------------------------------------------------------------------

def select_page3_articles(
    scored_articles: list[dict],
    *,
    displayed_urls_today: set[str] | None = None,
    displayed_urls_past_n: set[str] | None = None,
) -> tuple[dict[str, RegionSelection], int, int]:
    """全 scored articles に対して dedup → 領域振分け → 各領域 top1 を選定。

    Returns (selections, candidates_total, candidates_after_dedup)。
    selections は REGIONS 順で全 6 keys を含む（候補なし領域は article=None）。
    """
    if displayed_urls_today is None:
        displayed_urls_today = set()
    if displayed_urls_past_n is None:
        displayed_urls_past_n = set()

    # registry attach
    registry = _get_registry()
    for art in scored_articles:
        if not art.get("category"):
            name = art.get("source_name")
            if name:
                src = registry.sources_by_name.get(name)
                if src:
                    art["category"] = src.category

    candidates_total = len(scored_articles)

    # dedup：当日他面 + 過去 N 日 page3
    dedup_set = displayed_urls_today | displayed_urls_past_n
    if dedup_set:
        scored_articles = [
            a for a in scored_articles if a.get("url") not in dedup_set
        ]
    candidates_after_dedup = len(scored_articles)

    selections: dict[str, RegionSelection] = {}
    for region in REGIONS:
        pick = _select_top_for_region(scored_articles, region)
        if pick is None:
            selections[region] = RegionSelection(
                region=region, article=None, final_score=None,
                fallback_reason="no_candidates",
            )
        else:
            selections[region] = RegionSelection(
                region=region,
                article=pick,
                final_score=pick.get("final_score"),
                fallback_reason=None,
            )

    return selections, candidates_total, candidates_after_dedup


# ---------------------------------------------------------------------------
# Default fetcher (with Stage 2 sharing via pre_evaluated)
# ---------------------------------------------------------------------------

_HTML_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")


def _strip_html_simple(text: str | None) -> str:
    if not text:
        return ""
    no_tags = _HTML_TAG_RE.sub(" ", text)
    no_entities = (
        no_tags.replace("&nbsp;", " ").replace("&amp;", "&")
        .replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"')
    )
    return _WHITESPACE_RE.sub(" ", no_entities).strip()


# fetch + Stage1+2+3 を行う 4ファイル × 2優先度 = 8 取得対象。
# 各 (category, priority) ペアごとに ``scripts.fetch.run`` を1回ずつ呼ぶ。
PAGE3_FETCH_SCOPES: tuple[tuple[str, str], ...] = (
    ("business",    "high"),
    ("business",    "medium"),
    ("geopolitics", "high"),
    ("geopolitics", "medium"),
    ("academic",    "high"),
    ("academic",    "medium"),
    ("books",       "high"),
    ("books",       "medium"),
)


def default_fetcher(
    *,
    pre_evaluated: dict[str, dict] | None = None,
    limit: int = PER_FETCH_LIMIT,
) -> tuple[list[dict], float]:
    """fetch + Stage 1 + Stage 2 + Stage 3 → (scored_articles, cost_usd).

    ``pre_evaluated`` が渡されると、URL がそこに存在する記事は Stage 2 を
    再評価せず、保存済みの aesthetic / final_score 等のフィールドを流用
    する。第1面パイプラインで評価済の Foresight / Economist 記事のコスト
    を抑えるため。
    """
    from ..fetch import run as fetch_run

    raw_articles = []
    for cat, pri in PAGE3_FETCH_SCOPES:
        try:
            summary = fetch_run(
                category=cat, priority=pri, limit=limit,
                no_dedupe=True, write_log=False,
            )
            raw_articles.extend(summary.get("articles", []))
        except Exception as e:
            print(
                f"  [page3] fetch_run({cat}, {pri}) failed: {type(e).__name__}: {e}",
                file=sys.stderr,
            )

    # URL ベースで重複排除（複数 (category, priority) で同じ Source が拾われる
    # ことはないが、同一 URL が複数 sources にまたがる可能性は防御的に）。
    seen_urls: set[str] = set()
    pipeline_dicts: list[dict] = []
    for a in raw_articles:
        url = a.link or ""
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
        body = "\n".join(a.body_paragraphs) if a.body_paragraphs else ""
        pipeline_dicts.append({
            "url": url,
            "title": a.title,
            "description": _strip_html_simple(a.description),
            "body": _strip_html_simple(body),
            "source_name": a.source_name,
            "source_url": None,
            "pub_date": a.pub_date.isoformat() if a.pub_date else None,
        })

    # Stage 1
    s1_out = run_stage1(pipeline_dicts)
    surviving = [x for x in s1_out if not x.get("is_excluded")]
    if not surviving:
        return [], 0.0

    # Partition for Stage 2 sharing
    cached_articles: list[dict] = []
    uncached_articles: list[dict] = []
    for art in surviving:
        url = art.get("url")
        if url and pre_evaluated and url in pre_evaluated:
            # 既評価記事：page1 由来の評価結果（aesthetic + final_score）を被せる
            merged = dict(art)  # Stage 1 通過後の dict
            merged.update(pre_evaluated[url])  # stage2/stage3 fields を上書き
            cached_articles.append(merged)
        else:
            uncached_articles.append(art)

    cost = 0.0
    # Stage 2 (uncached 分のみ)
    if uncached_articles:
        s2 = run_stage2(uncached_articles)
        cost += s2.cost_usd
        integrate_scores(s2.evaluations_by_url)
        by_url = s2.evaluations_by_url
        scored_uncached: list[dict] = []
        for art in uncached_articles:
            url = art.get("url")
            if url and url in by_url:
                art.update(by_url[url])
                scored_uncached.append(art)
        cached_articles.extend(scored_uncached)

    # Attach category via registry
    registry = _get_registry()
    for art in cached_articles:
        if not art.get("category"):
            name = art.get("source_name")
            if name:
                src = registry.sources_by_name.get(name)
                if src:
                    art["category"] = src.category

    return cached_articles, cost


# ---------------------------------------------------------------------------
# Pipeline orchestration
# ---------------------------------------------------------------------------

def run_page3_pipeline(
    *,
    target_date: date | None = None,
    fetcher: Callable[..., tuple[list[dict], float]] | None = None,
    pre_evaluated: dict[str, dict] | None = None,
    displayed_urls_today: set[str] | None = None,
    displayed_urls_past_n: set[str] | None = None,
    write_log: bool = True,
) -> Page3Result:
    """End-to-end Page 3 pipeline。

    Parameters
    ----------
    target_date :
        生成対象日。logs/page3_*.json の日付に使う。
    fetcher :
        ``(*, pre_evaluated, limit) -> (articles, cost)`` 形式の関数。
        テスト時にモック差し替え。None なら ``default_fetcher`` を使う。
    pre_evaluated :
        {url: article_dict} 形式の Stage 2 共有キャッシュ。第1面で評価済の
        記事を再評価しないため。
    displayed_urls_today :
        当日 page1 / page2 で選定された URL の集合。dedup 対象。
    displayed_urls_past_n :
        過去 N=7 日に page3 で表示された URL の集合。dedup 対象。
    write_log :
        ``logs/page3_selection_<date>.json`` を書くか否か。
    """
    if target_date is None:
        target_date = date.today()
    if fetcher is None:
        fetcher = default_fetcher

    result = Page3Result(today=target_date)

    # Pre-flight cap check（コスト爆発の最終防衛線）
    cap = llm_usage.check_caps(target_date)
    if not cap.ok:
        print(f"[page3] daily cap reached: {cap.reason}", file=sys.stderr)
        for region in REGIONS:
            result.selections[region] = RegionSelection(
                region=region, article=None, final_score=None,
                fallback_reason=f"daily_cap_exceeded: {cap.reason}",
            )
        result.placeholder_count = len(REGIONS)
        return result

    # Fetch + Stage 1 + Stage 2 + Stage 3
    scored, cost = fetcher(
        pre_evaluated=pre_evaluated,
        limit=PER_FETCH_LIMIT,
    )
    result.cost_usd = round(cost, 6)

    # Selection
    selections, total, after_dedup = select_page3_articles(
        scored,
        displayed_urls_today=displayed_urls_today,
        displayed_urls_past_n=displayed_urls_past_n,
    )
    result.selections = selections
    result.candidates_total = total
    result.candidates_after_dedup = after_dedup
    result.placeholder_count = sum(
        1 for s in selections.values() if s.article is None
    )

    if result.placeholder_count >= 2:
        print(
            f"[page3] WARNING: {result.placeholder_count} regions resulted in "
            "「本日該当なし」 placeholder. Check logs/page3_selection_*.json "
            "for fallback reasons. (page3_design_v1.md §7 — 2 領域以上は要観察)",
            file=sys.stderr,
        )

    if write_log:
        write_page3_log(result)

    return result


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def _page3_log_path(d: date | None = None) -> Path:
    return LOG_DIR / f"page3_selection_{(d or date.today()).isoformat()}.json"


def write_page3_log(result: Page3Result) -> Path:
    today = result.today or date.today()
    path = _page3_log_path(today)
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    selections_log: dict[str, Any] = {}
    for region in REGIONS:
        sel = result.selections.get(region)
        if sel is None:
            continue
        if sel.article is None:
            selections_log[region] = {
                "region": region,
                "display_name": REGION_DISPLAY_NAMES[region],
                "article": None,
                "fallback_reason": sel.fallback_reason,
            }
        else:
            art = sel.article
            selections_log[region] = {
                "region": region,
                "display_name": REGION_DISPLAY_NAMES[region],
                "article": {
                    "url": art.get("url"),
                    "title": art.get("title"),
                    "source_name": art.get("source_name"),
                    "category": art.get("category"),
                    "final_score": art.get("final_score"),
                    "aesthetic_scores": {
                        k: art.get(k) for k in ("美意識1", "美意識3", "美意識5", "美意識6", "美意識8")
                    },
                    "美意識2_machine": art.get("美意識2_machine"),
                    "pub_date": art.get("pub_date"),
                },
                "kicker": _generate_kicker(art, region),
                "fallback_reason": None,
            }

    data = {
        "date": today.isoformat(),
        "candidates_total": result.candidates_total,
        "candidates_after_dedup": result.candidates_after_dedup,
        "placeholder_count": result.placeholder_count,
        "cost_usd": round(result.cost_usd, 6),
        "selections": selections_log,
        "generated_at": _now_iso(),
    }
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path
