"""月次選定主軸記事の読み込み + 週/曜日/角度判定（Phase 3, 2026-05-23）.

``data/monthly_pivotal.json`` から「当該日が属する週」「曜日に対応する論考
角度」「来週分（土曜の予告用）」を取り出すユーティリティ群。

7 日間構造（仕様 §4.2）：
    日 → overview     全体像
    月 → critical     批判的
    火 → practitioner 実践者
    水 → thinker      思想家
    木 → history      歴史
    金 → integration  統合＋問い
    土 → response     応答（神山さんコメント → AIかみやま）

LLM は呼ばない（純粋なファイル I/O + 日付判定のみ）。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path

DEFAULT_PIVOTAL_PATH = (
    Path(__file__).resolve().parent.parent.parent / "data" / "monthly_pivotal.json"
)


# 曜日 (date.weekday(): 月=0..日=6) → (日本語ラベル, angle_key, 日本語角度ラベル)。
# 1 週間 = 日曜開始 - 土曜終了。
_ANGLE_BY_WEEKDAY: dict[int, tuple[str, str, str]] = {
    6: ("日", "overview",     "全体像"),
    0: ("月", "critical",     "批判的"),
    1: ("火", "practitioner", "実践者"),
    2: ("水", "thinker",      "思想家"),
    3: ("木", "history",      "歴史"),
    4: ("金", "integration",  "統合＋問い"),
    5: ("土", "response",     "応答"),
}

# 仕様 §4.6 用語解説型補助セクションのラベル（角度ごと）。
ANNOTATION_LABEL_BY_ANGLE: dict[str, str] = {
    "overview":     "主要キーワード",
    "critical":     "反対論者・批判者",
    "practitioner": "関連企業・事例",
    "thinker":      "中心思想家と主著",
    "history":      "歴史的事象・年表",
    "integration":  "1 週間の論点総括",
    "response":     "1 週間の問い一覧",  # 土曜のみ、参考用
}


@dataclass
class WeekContext:
    """ある target_date が属する週の文脈一式."""
    week_label: str             # "W1" など、monthly_pivotal.json の key
    theme: str                  # "AIと暗黙知"
    period: tuple[date, date]   # (日曜, 土曜)
    article: dict               # title/source/author/url/published/summary/key_quote(_ja)/points/angles_hints
    day_label: str              # "日"/"月"/.../"土"
    angle_key: str              # "overview" 等
    angle_label_jp: str         # "全体像" 等

    def history_key(self) -> str:
        """logs/page1_v3_history.json での週 unique key（再利用想定の年跨ぎ対応）."""
        return f"{self.week_label}_{self.period[0].isoformat()}"


def load_monthly_pivotal(path: Path | None = None) -> dict:
    """JSON を読み込んで返す。存在しない / 壊れている場合は ``{}`` を返す（caller が graceful 判定）."""
    p = path or DEFAULT_PIVOTAL_PATH
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def angle_for_day(target: date) -> tuple[str, str, str]:
    """曜日 → (day_label, angle_key, angle_label_jp)."""
    return _ANGLE_BY_WEEKDAY[target.weekday()]


def _parse_period(period_raw: object) -> tuple[date, date] | None:
    """JSON 上の period（["YYYY-MM-DD", "YYYY-MM-DD"]）を date タプルに."""
    if not isinstance(period_raw, list) or len(period_raw) != 2:
        return None
    try:
        start = date.fromisoformat(period_raw[0])
        end = date.fromisoformat(period_raw[1])
    except (TypeError, ValueError):
        return None
    if end < start:
        return None
    return (start, end)


def find_week_for_date(target: date, monthly: dict) -> WeekContext | None:
    """target が属する週を返す。未投入 / 該当なしなら None（caller は v2 fallback）.

    主軸記事の必須フィールド（title / url）が欠けていたら None を返す
    （月次選定セッション未了の week placeholder を弾く）。
    """
    weeks = monthly.get("weeks") or {}
    for week_label, week in weeks.items():
        if not isinstance(week, dict):
            continue
        period = _parse_period(week.get("period"))
        if period is None:
            continue
        start, end = period
        if not (start <= target <= end):
            continue
        article = week.get("article") or {}
        title = (article.get("title") or "").strip()
        url = (article.get("url") or "").strip()
        if not title or not url:
            return None  # 月次選定未了
        day_label, angle_key, angle_label_jp = angle_for_day(target)
        return WeekContext(
            week_label=week_label,
            theme=str(week.get("theme") or "").strip(),
            period=period,
            article=article,
            day_label=day_label,
            angle_key=angle_key,
            angle_label_jp=angle_label_jp,
        )
    return None


def find_next_week(current: WeekContext, monthly: dict) -> WeekContext | None:
    """current の翌週（period[1] + 1 日が属する週）を返す。未投入なら None.

    土曜の「来週予告」セクション用（仕様 §4.9）。来週分が monthly_pivotal.json
    に無ければ呼び出し側で placeholder を出す。
    """
    from datetime import timedelta

    next_start = current.period[1] + timedelta(days=1)
    # 翌週起点（日曜）の context を要求するが、find_week_for_date は target が
    # period に含まれていれば返す。next_start は次週の日曜である想定。
    return find_week_for_date(next_start, monthly)
