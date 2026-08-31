"""5面 AIかみやま参照記事の未出優先と dedup 窓 (C190, 2026-08-31).

背景
----
神山さんが「今朝の自殺の記事、あと Occupy Wall Street も数日前に出ていた」と
気づいた。実データを走査したところ、全 120 日で重複 3 件、**うち C168 以降が
2 件**で、どちらもちょうど 9 日間隔だった::

    2026-08-14  thepointmag /we-were-the-99-percent/      初出
    2026-08-17  同上                              (3 日)  C167/C168 の発端
    2026-08-26  同上                              (9 日)  ★3 回目
    2026-08-22  publicbooks /literature-in-the-time-of-suicide/
    2026-08-31  同上                              (9 日)  ★今朝

C168 は仕様どおり動いていた（7 日以内は弾いていた）が、``PAGE5_DEDUP_DAYS = 7``
の窓が短すぎた。7 にしたのは「3 面の dedup 窓が 7 日だから意味が揃う」という
概念的な対称性が理由で、必要性からではなかった。5 面の候補プール（3 面
runner-up）は 3 面より狭いため、同じ窓では足りない。

30 日窓の安全性は C168 が既に実測していた（残候補 17-20 件、必要なのは
top_n=5）。当時のコミットにも「強めたければ定数 1 行を伸ばせばよい」とある。

さらに、窓を伸ばしても**高スコア記事は窓を抜けた瞬間に戻ってくる**（99% 記事は
8/14-8/17 の 4 日間ずっと top_n=5 圏内に居続けていた）。そこで 4 面の概念選出
（C188）と同じ 3 段構えにした:

    段 1  過去 PAGE5_DEDUP_DAYS 日に出た URL を除外
    段 2  未出（全期間で一度も 5 面に出ていない）を優先
    段 3  未出が尽きたら既出から選ぶ（再訪）

Tests:
  a) 定数が広がっている
  b) 未出があれば必ず未出から選ばれる
  c) 未出が尽きたら既出から選ぶ（空にしない）
  d) ever_used_urls 未指定なら従来動作（後方互換）
  e) 段 1 と段 2 が両方効く
  f) 実データ回帰: 観測された 2 件が新しい窓・未出判定で捕まる

Run::

    python3 -m tests.page5.test_ai_kamiyama_unseen_first
"""

from __future__ import annotations

import glob
import io
import json
import os
import random
import sys
from contextlib import redirect_stderr
from datetime import date, timedelta
from pathlib import Path

from scripts.page5.ai_kamiyama_selector import select_ai_kamiyama_article
from scripts.regen_front_page_v2 import (
    PAGE5_DEDUP_DAYS,
    PAGE5_UNSEEN_LOOKBACK_DAYS,
)

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


def _pool(n=8):
    return [{"url": f"u{i}", "final_score": 100 - i, "title": f"t{i}"}
            for i in range(n)]


def _pick(pool, *, ever=None, exclude=None, seed=0):
    buf = io.StringIO()
    with redirect_stderr(buf):
        a = select_ai_kamiyama_article(
            target_date=date(2026, 9, 1), page3_selections={},
            page3_runner_ups=pool, ever_used_urls=ever,
            exclude_urls=exclude, rng=random.Random(seed))
    return (a or {}).get("url"), buf.getvalue()


# ---------------------------------------------------------------------------
# (a) 定数
# ---------------------------------------------------------------------------

def test_constants():
    _check("a1 PAGE5_DEDUP_DAYS が 30 に広がっている",
           PAGE5_DEDUP_DAYS == 30, str(PAGE5_DEDUP_DAYS))
    _check("a2 観測された 9 日間隔の重複を覆える（> 9）",
           PAGE5_DEDUP_DAYS > 9, str(PAGE5_DEDUP_DAYS))
    _check("a3 全期間の遡りが運用開始 2026-04-25 をカバーする",
           PAGE5_UNSEEN_LOOKBACK_DAYS >= 365, str(PAGE5_UNSEEN_LOOKBACK_DAYS))


# ---------------------------------------------------------------------------
# (b) 未出優先
# ---------------------------------------------------------------------------

def test_prefers_unseen():
    pool = _pool()
    ever = {"u0", "u1", "u2"}          # 高スコア上位 3 件が既出
    picks = {_pick(pool, ever=ever, seed=s)[0] for s in range(40)}
    _check("b1 既出（高スコアでも）は選ばれない", not (picks & ever),
           str(sorted(picks)))
    _check("b2 未出からのみ選ばれる", picks <= {"u3", "u4", "u5", "u6", "u7"},
           str(sorted(picks)))


def test_unseen_wins_even_when_scored_lower():
    """スコアが低くても未出が優先されること（本件の核心）."""
    pool = _pool(6)
    ever = {"u0", "u1", "u2", "u3", "u4"}   # 未出は最下位スコアの u5 だけ
    for s in range(20):
        u, _ = _pick(pool, ever=ever, seed=s)
        if u != "u5":
            _check("b3 未出が 1 件でもあればそれが選ばれる", False, str(u))
            return
    _check("b3 未出が 1 件でもあればそれが選ばれる", True, "u5 ×20")


def test_logs_unseen_stage():
    _, log = _pick(_pool(), ever={"u0", "u1"})
    _check("b4 未出優先に入ったことが記録される", "未出優先" in log,
           log.strip()[:70])


# ---------------------------------------------------------------------------
# (c) 再訪
# ---------------------------------------------------------------------------

def test_revisit_when_all_seen():
    pool = _pool()
    ever = {f"u{i}" for i in range(8)}
    picks = {_pick(pool, ever=ever, seed=s)[0] for s in range(20)}
    _check("c1 全部既出でも選出は空にならない", picks and None not in picks,
           str(sorted(picks)))
    _, log = _pick(pool, ever=ever)
    _check("c2 未出が尽きたことを知らせる（供給確認のシグナル）",
           "未出の候補が尽きました" in log, log.strip()[:70])


# ---------------------------------------------------------------------------
# (d) 後方互換
# ---------------------------------------------------------------------------

def test_backward_compatible():
    pool = _pool()
    picks = {_pick(pool, seed=s)[0] for s in range(20)}
    _check("d1 ever_used_urls 未指定なら従来どおり top_n から選ぶ",
           picks <= {"u0", "u1", "u2", "u3", "u4"}, str(sorted(picks)))
    _, log = _pick(pool)
    _check("d2 未指定時は未出ログを出さない", "未出" not in log)


# ---------------------------------------------------------------------------
# (e) 段 1 と段 2 の併用
# ---------------------------------------------------------------------------

def test_both_stages_apply():
    pool = _pool()
    # u0,u1 は直近 30 日（段 1 で除外）／u2,u3 は既出だが窓外（段 2 で除外）
    picks = {_pick(pool, exclude={"u0", "u1"},
                   ever={"u0", "u1", "u2", "u3"}, seed=s)[0]
             for s in range(30)}
    _check("e1 段 1 の除外が効く", not (picks & {"u0", "u1"}), str(sorted(picks)))
    _check("e2 段 2 の除外も同時に効く", not (picks & {"u2", "u3"}),
           str(sorted(picks)))
    _check("e3 残りから選ばれる", picks <= {"u4", "u5", "u6", "u7"},
           str(sorted(picks)))


# ---------------------------------------------------------------------------
# (f) 実データ回帰
# ---------------------------------------------------------------------------

def test_observed_duplicates_now_caught():
    root = Path(__file__).resolve().parents[2]
    hist = {}
    for f in sorted(glob.glob(str(root / "logs" / "displayed_urls_2026-*.json"))):
        d = os.path.basename(f)[:-5].replace("displayed_urls_", "")
        try:
            u = json.loads(Path(f).read_text(encoding="utf-8")).get("page5_url")
        except Exception:
            u = None
        if u:
            hist[d] = u

    def window(target, days):
        t = date.fromisoformat(target)
        return {u for d, u in hist.items()
                if t - timedelta(days=days) <= date.fromisoformat(d)
                <= t - timedelta(days=1)}

    cases = [("2026-08-26", "Occupy Wall Street 3 回目"),
             ("2026-08-31", "自殺の記事 2 回目")]
    for target, label in cases:
        if target not in hist:
            _check(f"f {label}: ログが存在", False, target)
            continue
        actual = hist[target]
        _check(f"f1 {label} は旧 7 日窓では捕まらなかった",
               actual not in window(target, 7))
        _check(f"f2 {label} は新 {PAGE5_DEDUP_DAYS} 日窓で捕まる",
               actual in window(target, PAGE5_DEDUP_DAYS))
        _check(f"f3 {label} は未出判定でも捕まる（二重の防御）",
               actual in window(target, PAGE5_UNSEEN_LOOKBACK_DAYS))


def main() -> int:
    print("C190: 5面 AIかみやま参照記事の未出優先と dedup 窓\n")
    print("(a) 定数:")
    test_constants()
    print()
    print("(b) 未出優先:")
    test_prefers_unseen()
    test_unseen_wins_even_when_scored_lower()
    test_logs_unseen_stage()
    print()
    print("(c) 再訪:")
    test_revisit_when_all_seen()
    print()
    print("(d) 後方互換:")
    test_backward_compatible()
    print()
    print("(e) 段 1 と段 2 の併用:")
    test_both_stages_apply()
    print()
    print("(f) 実データ回帰:")
    test_observed_duplicates_now_caught()
    print()
    print(f"=== {PASS} passed, {FAIL} failed ===")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
