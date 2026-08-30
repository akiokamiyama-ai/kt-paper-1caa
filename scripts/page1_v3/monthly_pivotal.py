"""月次選定主軸記事の読み込み + 週/曜日/角度判定（Phase 3, 2026-05-23）.

``data/monthly_pivotal.json`` から「当該日が属する週」「曜日に対応する論考
角度」「来週分（土曜の予告用）」を取り出すユーティリティ群。

7 日間構造（仕様 §4.2）。C187 (2026-08-29) で並びを変更した：

    曜日   ANGLE_ORDER_V2（W16 以降）   ANGLE_ORDER_V1（W15 まで）
    日     overview     全体像          overview     全体像
    月     history      歴史的経緯      critical     批判的
    火     critical     批判的          practitioner 実践者
    水     thinker      思想家          thinker      思想家
    木     practitioner 実践者          history      歴史
    金     integration  統合＋問い      integration  統合＋問い
    土     response     応答            response     応答

V2 の意図（神山さん判断）:

* **history を月曜へ前倒し** —— 「この問題はどこから来たか」を先に知ってから
  批判に入る方が批判の解像度が上がる。V1 では月曜の批判の根拠が木曜に後から
  補強される形になっていた
* **practitioner を木曜へ後ろ倒し** —— 思想家（水）の議論を経てから実践に
  落とす方が具体性が出る。V1 では火曜の実践論が水木の深い議論に接続されない
  まま終わっていた

切替は ``ANGLE_ORDER_V2_FROM`` の日付境界で行う。W15（8/30-9/5）は既に
日曜 overview で走り出しており、週の途中でマッピングを変えると
``angles_hints`` と紙面がずれるため、W16 開始（9/6 日曜）から有効化する。

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

# C187 以前の並び。W15（〜2026-09-05）まではこちらで走る。
_ANGLE_BY_WEEKDAY_V1: dict[int, tuple[str, str, str]] = {
    6: ("日", "overview",     "全体像"),
    0: ("月", "critical",     "批判的"),
    1: ("火", "practitioner", "実践者"),
    2: ("水", "thinker",      "思想家"),
    3: ("木", "history",      "歴史"),
    4: ("金", "integration",  "統合＋問い"),
    5: ("土", "response",     "応答"),
}

# C187 (2026-08-29) の新しい並び。history を月曜へ、practitioner を木曜へ。
_ANGLE_BY_WEEKDAY_V2: dict[int, tuple[str, str, str]] = {
    6: ("日", "overview",     "全体像"),
    0: ("月", "history",      "歴史的経緯"),
    1: ("火", "critical",     "批判的"),
    2: ("水", "thinker",      "思想家"),
    3: ("木", "practitioner", "実践者"),
    4: ("金", "integration",  "統合＋問い"),
    5: ("土", "response",     "応答"),
}

# V2 を有効化する日（この日を含む、JST の紙面日付で判定）。
# W16 の Day 1（日曜）。週の途中で切り替えると angles_hints とずれるため、
# 必ず日曜に合わせること。
#
# 移行が済んで W15 以前を再生成する必要が無くなったら、V1 と本定数ごと消して
# _ANGLE_BY_WEEKDAY_V2 を唯一のマップにしてよい。
ANGLE_ORDER_V2_FROM: date = date(2026, 9, 6)

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
    """曜日 → (day_label, angle_key, angle_label_jp).

    C187: ``ANGLE_ORDER_V2_FROM`` 以降は新しい並び（月=history / 火=critical /
    木=practitioner）を返す。それ以前の日付は従来どおり。過去日を再生成した
    ときに当時の紙面と角度がずれないよう、日付で切り替えている。
    """
    table = (
        _ANGLE_BY_WEEKDAY_V2 if target >= ANGLE_ORDER_V2_FROM
        else _ANGLE_BY_WEEKDAY_V1
    )
    return table[target.weekday()]


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
