"""AIかみやま 専用の記事選定（Sprint 7 Phase 1 Step 1, 2026-05-18）.

Sprint 7 で第5面を「上：serendipity / 下：AIかみやま column」の上下分離構造
に再設計するための前提。AIかみやま のコメント対象記事を、serendipity 記事
ではなく独立に選定する。

# Sprint 8 C40 第二弾 (2026-05-30) — 設計変更

旧設計（Sprint 7）：
- 候補プール = ``candidates_scored``（Page I pipeline の Stage 2 評価済記事
  数百件）から ``excluded_urls`` (Page I/III/IV/serendipity 採用済) を引いた残り
- 弱点：紙面に出ていない記事を選んでしまい、編集後記（C45 で別途対策）と同じく
  「読者が照合できない引用」が発生。さらに過去日 dedup が無いため 5/29-5/30 で
  同一 BBC URL (czx2qll4rlyo) を連続表示。

新設計（神山案、C40 第二弾）：
- 候補プール = **当日確定紙面の記事のみ**（Page II Today's Headlines + Page III
  R1-R6 + Page IV 学術記事）
- Page I は意図的に除外（v3 swap で essay 形式に置換される or v2 でも editorial
  との整合性のため、C45 D2 と同じ哲学）
- Page V serendipity は AIかみやま と背中合わせなので除外
- 過去日 dedup は不要：当日紙面は他面の dedup（C40 案1+案2 で headlines、page3
  は 7 日、page4 は 30 日）により既に過去重複から保護されている

# C168 (Sprint 13, 2026-08-17) — 上記「過去日 dedup は不要」の前提は誤りだった

C167 調査で、C40 の想定「他面 dedup に相乗りすれば連続日重複は自動解決する」が
**実際には機能していなかった**ことが判明した。archive 全期間（2026-04-25〜08-17、
5 面参照記事 100 ユニーク URL）を走査した結果、日跨ぎ重複は **6 件**:

    5/22→5/23  5/29→5/30  6/20→6/21  7/02→7/05  8/03→8/04   （C155 前、5 件）
    8/14→8/17                                                （C161 後、1 件）

5/29-30 の BBC 重複は C40 第二弾を生んだ事象そのものだが、その対策後も
6/20 / 7/02 / 8/03 と再発し続けていた。他面の dedup 窓（page3 7 日）を超えた
記事が候補に戻ってくるため、相乗りでは防ぎきれない。

さらに C161 で候補プールを page3 runner-up のみにしたことで、**相乗り先が
完全に消えた**。runner-up は「3 面に載らなかった記事」なので
``displayed_urls`` の ``page3_urls`` に記録されず、どの面の dedup にも
引っかからない。8/14→8/17 の重複はこれで起きた（当該 URL は 4 日間ずっと
候補プールの top 5 圏内に居り、8/15・8/16 に選ばれなかったのは
``rng.choice`` の抽選に外れただけ）。

対処として **5 面自身の過去 N 日 dedup** を入れた（``PAGE5_DEDUP_DAYS``）。
書き手（``write_displayed_urls_log(page5_url=...)``）と読み手
（``load_recently_displayed_urls(page="page5")``）は以前から実装済で、
呼び出す人がいなかっただけである。

設計上のメリット
----------------
- 紙面の内的整合性が保たれる（AIかみやま が引く記事は読者が紙面で発見できる）
- ロジックが単純化（pre-evaluated 候補プールへの依存が消える）
"""

from __future__ import annotations

import random
import sys
from datetime import date
from typing import Any

from ..selector.source_registry import SourceRegistry


# C40 第二弾以降は category フィルタの必要性は薄れた（候補プール自体が紙面確定
# 記事 = 既に編集判断を通過している）。後方互換のため定数は残すが、caller は
# 通常 None を渡してフィルタ無しで使うのが推奨。
AI_KAMIYAMA_CATEGORIES: tuple[str, ...] = (
    "business",
    "geopolitics",
    "academic",
    "books",
    "culture",
)

# 上位 N 件から random 選定。候補プールが小さくなった C40 第二弾でも、
# top_n=5 までは概ね埋まる（Page II headlines 3 + Page III 6 + Page IV 3 = 最大 12）。
DEFAULT_TOP_N: int = 5


def _article_category(
    article: dict, registry: SourceRegistry | None
) -> str | None:
    """article の source_name から category を引く。article に既に
    ``category`` フィールドがあれば優先（page4 等は事前付与）.
    """
    cat = article.get("category")
    if cat:
        # source.category は "companies:Cocolomi" のように prefix を持つ
        # 場合がある。base category（":" 前）に揃える。
        return cat.split(":", 1)[0]
    if registry is None:
        return None
    name = article.get("source_name") or ""
    src = registry.sources_by_name.get(name)
    if src is None:
        return None
    return src.category.split(":", 1)[0]


def _collect_page3_articles(page3_selections: Any | None) -> list[dict]:
    """Page III の RegionSelection 群から非 None article を取り出す.

    RegionSelection は dataclass で ``.article`` を持つ。dict 形式
    ``{"article": {...}}`` にも対応（テスト容易性）。
    """
    out: list[dict] = []
    if not page3_selections:
        return out
    for _region, sel in page3_selections.items():
        art = getattr(sel, "article", None)
        if art is None and isinstance(sel, dict):
            art = sel.get("article")
        if art and isinstance(art, dict):
            out.append(art)
    return out


def build_candidate_pool(
    *,
    page3_selections: Any | None = None,
    page3_runner_ups: list[dict] | None = None,
) -> list[dict]:
    """AIかみやま の候補プールを構築する.

    C161 (Sprint 13, 2026-08-13): **Page III の確定 6 枠を候補から除外**し、
    runner-up（3 面に載らなかった評価済み上位候補）のみを候補にする。

    経緯:
        C155 で第5面を一筆 100% にした際、候補プールを「Page III 確定 6 枠 +
        runner-up」とした。旧構成にあった「同じ記事を二度出さない」制約
        （serendipity との背中合わせルール）は、セレンディピティが 3 面の
        1 枠になって「背中合わせ」でなくなったため廃止した。

        その副作用として **3 面と 5 面に同じ記事が出る**事象が発生した。
        C160 観察（8/11-13）では 3 日中 2 日（67%）で重複：
            8/12 SER 枠と同一 / 8/13 R6 と同一
        確定枠は各領域のトップスコアなのでスコア降順の top_n に入りやすく、
        構造上高頻度で起きる。セレンディピティ固有の問題ではなかった。

        よって確定枠を候補から外す。第5面は「3 面に載らなかった惜しい記事に
        光を当てる」枠になり、紙面全体での記事の露出が広がる。

    枯渇について:
        runner-up は ``RUNNER_UP_POOL_SIZE=20`` 件上限で、Page III は通常
        250 件前後の候補を採点している（8/13 実測: dedup 後 253 件）。
        通常運用で枯渇はまず起きない。それでも Page III の fetch が総崩れした
        日などに備え、runner-up が空なら**確定枠に戻す**（``_FALLBACK`` を
        参照）。重複した記事が出るほうが第5面が白紙になるより良い。

    Page I は引き続き意図的に含めない（C45 D2 と同じ哲学：週次 essay は
    editorial / 一筆と参照が重複するため）。

    Parameters
    ----------
    page3_selections :
        ``Page3Result.selections`` (dict[str, RegionSelection])。
        **通常は候補に含めない。** runner-up が空のときの fallback にのみ使う。
    page3_runner_ups :
        ``Page3Result.runner_up_candidates``。3 面に載らなかった上位候補。
        これが主候補。

    Returns
    -------
    list[dict]
        URL を持つ candidate article の順序保持リスト。
    """
    def _dedupe(items: list[dict]) -> list[dict]:
        seen: set[str] = set()
        out: list[dict] = []
        for a in items:
            url = (a or {}).get("url")
            if not url or url in seen:
                continue
            seen.add(url)
            out.append(a)
        return out

    pool = _dedupe(list(page3_runner_ups or []))
    if pool:
        return pool

    # Fallback: runner-up が 1 件も無い異常時のみ確定枠に戻す。
    # 3 面と重複するが、第5面が白紙になるより良い（C155 のフェイルセーフ哲学）。
    fallback = _dedupe(_collect_page3_articles(page3_selections))
    if fallback:
        print(
            "[ai_kamiyama] WARN: runner-up が 0 件のため Page III 確定枠に "
            f"fallback します（{len(fallback)} 件）。3 面と同じ記事が 5 面に "
            "出る可能性があります（C161）。Page III の fetch 状況を確認してください。",
            file=sys.stderr,
        )
    return fallback


def select_ai_kamiyama_article(
    *,
    target_date: date,
    page3_selections: Any | None = None,
    page3_runner_ups: list[dict] | None = None,
    exclude_urls: set[str] | None = None,
    ever_used_urls: set[str] | None = None,
    registry: SourceRegistry | None = None,
    eligible_categories: tuple[str, ...] | None = None,
    rng: random.Random | None = None,
    top_n: int = DEFAULT_TOP_N,
) -> dict | None:
    """AIかみやま 専用の記事選定（C40 第二弾 → C155 → C161）.

    候補プールは Page III で採用されなかった評価済み上位候補
    （``Page3Result.runner_up_candidates``）**のみ**。C161 で Page III の
    確定 6 枠を除外し、3 面と 5 面に同じ記事が出る事象を構造的に断った。
    詳細は ``build_candidate_pool`` の docstring を参照。

    Page I は意図的に対象外（C45 D2 と同じ哲学：週次 essay は editorial /
    一筆と参照が重複するため）。

    Parameters
    ----------
    target_date :
        対象日（将来 Phase 3 のテーマ判定で使う想定、現状は使用しない）。
    page3_selections :
        ``Page3Result.selections``。C161 以降は **runner-up が空のときの
        fallback 用**にのみ使う（通常は候補に入らない）。
    page3_runner_ups :
        ``Page3Result.runner_up_candidates``。C161 以降はこれが主候補。
    exclude_urls :
        C168: 過去 ``PAGE5_DEDUP_DAYS`` 日に 5 面で採用した URL の集合。
    ever_used_urls :
        C190: **全期間**で一度でも 5 面に採用した URL の集合。未出優先
        （段 2）の判定に使う。None なら段 2 を飛ばして従来どおり全候補から
        選ぶ（後方互換）。
        候補から除外して日跨ぎ重複を防ぐ。除外後に候補が 0 件になる場合は
        **除外を諦めて元の候補に戻す**（白紙より重複、C161 の fallback と
        同じ思想）。呼出側が ``load_recently_displayed_urls(page="page5")``
        で算出して渡す。
    registry :
        source category 解決用。``None`` の場合は category フィルタを skip。
        C40 第二弾以降、候補プールが既に編集判断を通っているため通常 None で
        十分。
    eligible_categories :
        category フィルタ対象。``None`` または空タプルなら全 category 許可。
        C40 第二弾以降は通常 None で運用するのが推奨。
    rng :
        テスト用の random.Random。None ならグローバル random を使う。
    top_n :
        上位何件から random 選定するか。default ``DEFAULT_TOP_N=5``。

    Returns
    -------
    dict | None
        選ばれた article dict、または候補ゼロで None。
    """
    pool = build_candidate_pool(
        page3_selections=page3_selections,
        page3_runner_ups=page3_runner_ups,
    )
    if not pool:
        return None

    # C168: 5 面自身の過去日 dedup。C40 が想定した「他面 dedup への相乗り」は
    # 実際には機能していなかった（module docstring 参照）。
    if exclude_urls:
        kept = [a for a in pool if a.get("url") not in exclude_urls]
        if kept:
            removed = len(pool) - len(kept)
            if removed:
                print(
                    f"[ai_kamiyama] 過去 {len(exclude_urls)} URL と重複する "
                    f"{removed} 件を候補から除外（残り {len(kept)} 件）",
                    file=sys.stderr,
                )
            pool = kept
        else:
            # 除外後 0 件。白紙にするより重複を許す（C161 fallback と同じ思想）。
            print(
                f"[ai_kamiyama] WARN: 過去日 dedup で候補が 0 件になったため "
                f"除外を諦めます（候補 {len(pool)} 件すべてが過去 5 面に既出）。"
                "日跨ぎ重複が発生します。runner-up の供給状況を確認してください。",
                file=sys.stderr,
            )

    # ------------------------------------------------------------------
    # C190 (2026-08-31): 段 2 = 未出優先 / 段 3 = 再訪
    #
    # 段 1（上の exclude_urls）だけでは、窓を抜けた高スコア記事がすぐ戻って
    # くる。実際 thepointmag /we-were-the-99-percent/ は 8/14・8/17・8/26 と
    # **3 回**選ばれた。スコアが高い記事は窓の外に出た瞬間また top_n 圏内に
    # 入るためで、窓を伸ばしても「31 日目に再登場」は起こりうる。
    #
    # そこで 4 面の概念選出（C188）と同じ構えにする。未出があるうちは未出
    # だけから選び、尽きたら既出に戻る。既出を永久に封印しないのは、候補が
    # 3 面 runner-up という狭い供給に依存していて在庫切れが現実的にありうる
    # ため（4 面は 268 件のプールがあるが、こちらは日々 20 件前後）。
    # ------------------------------------------------------------------
    if ever_used_urls:
        unseen = [a for a in pool if a.get("url") not in ever_used_urls]
        if unseen:
            if len(unseen) < len(pool):
                print(
                    f"[ai_kamiyama] 未出優先: {len(pool)} 件中 {len(unseen)} 件が"
                    "未出。ここから選びます",
                    file=sys.stderr,
                )
            pool = unseen
        else:
            print(
                f"[ai_kamiyama] 未出の候補が尽きました（{len(pool)} 件すべて"
                "過去に 5 面で採用済み）。既出からの再訪に切り替えます"
                "—— runner-up の供給状況を確認してください",
                file=sys.stderr,
            )

    if rng is None:
        rng = random.Random()

    # Optional category filter（C40 第二弾以降は通常 skip 推奨）
    if eligible_categories:
        filtered = [
            a for a in pool
            if _article_category(a, registry) in eligible_categories
        ]
        if filtered:
            pool = filtered
        # filtered が空ならフィルタ無視で pool 全体を残す（候補枯渇を避ける）

    # final_score で降順ソート（None は最下位扱い）
    def _score(a: dict) -> float:
        s = a.get("final_score")
        return s if isinstance(s, (int, float)) else float("-inf")
    pool.sort(key=_score, reverse=True)

    # 上位 top_n から random 選定
    n = min(top_n, len(pool))
    if n <= 0:
        return None
    return rng.choice(pool[:n])
