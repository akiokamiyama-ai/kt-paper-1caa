"""Tribune の「編集日」= JST 日付を返す単一の情報源（C159, Sprint 13, 2026-08-12）。

なぜ必要か
----------
GHA runner は UTC で動く。cron は 17:37 UTC（= 02:37 JST 翌日）に起動するため、
``date.today()`` を素で使うと **ログのファイル名が紙面の日付より 1 日古くなる**。

この事故は過去 2 回、別々の Sprint で個別に修正されてきた：

* Sprint 6 Phase 1 (2026-05-10) — ``llm_usage_*.json``
  5/10 朝刊のコストが ``llm_usage_2026-05-09.json`` に入っていた
* C88 (Sprint 10, 2026-06-16) — ``stage2_shadow_*.json``
  6/16 朝刊分の shadow ログが ``stage2_shadow_2026-06-15.json`` になっていた

C159 で 3 回目（``scores_*.json``）が見つかった。C155a / C157 / C158 の調査で
「8/12 の紙面データが scores_2026-08-11.json に入る」ことに毎回つまずいたため、
同じ実装を各所にコピーするのをやめ、本 module に一本化する。

使い方
------
ログのファイル名や履歴の日付に「今日」を使う箇所は、``date.today()`` ではなく
``jst_today()`` を呼ぶこと。呼び出し側が明示的な ``target_date`` を持っている
場合は**そちらを優先**する（``--date`` 経由で渡る紙面日付が最も信頼できる）。
本 module はあくまで **デフォルト値**のための最終手段。
"""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

JST = ZoneInfo("Asia/Tokyo")


def jst_today() -> date:
    """Tribune の編集日（JST の今日）を返す。"""
    return datetime.now(JST).date()


def jst_now_iso() -> str:
    """現在の JST タイムスタンプ（秒精度、タイムゾーン接尾辞なし）。"""
    return datetime.now(JST).replace(tzinfo=None).isoformat(timespec="seconds")
