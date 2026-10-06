"""shadow 評価の起動口 (C211, 2026-10-05).

紙面を落とさないための約束
--------------------------
1. ``TRIBUNE_SHADOW_SCORER`` が未設定なら **何もしない**（既定で完全に無効）
2. 入口の ``maybe_run_shadow`` が全体を try/except で包む。
   shadow 側の例外は一切外に出さない
3. 本番の評価結果（``articles`` / ``evaluations``）を**書き換えない**
4. 書き込むのは ``logs/shadow_eval_<date>.json`` だけ

C201 の「通知は best-effort、起動は必達」と同じ原則。
"""

from __future__ import annotations

import os
import sys

from .base import AESTHETIC_KEYS, ShadowScorer

ENV_SCORER = "TRIBUNE_SHADOW_SCORER"
ENV_LIMIT = "TRIBUNE_SHADOW_LIMIT"
DEFAULT_LIMIT = 10


def _build_scorer(name: str) -> ShadowScorer | None:
    name = (name or "").strip().lower()
    if name in ("jev", "jev-latest"):
        from .jev import JevScorer
        return JevScorer()
    if name in ("jev_fulltext", "jev-fulltext"):
        from .jev import JevFullTextScorer
        return JevFullTextScorer()
    return None


def _build_scorers(spec: str) -> list[ShadowScorer]:
    """C214: カンマ区切りで複数の scorer を並走させる.

    ``TRIBUNE_SHADOW_SCORER: jev,jev_fulltext`` で A/B 両方を走らせる。
    未知の名前は skip して残りを走らせる（1 つの typo で全部止めない）。
    """
    out: list[ShadowScorer] = []
    for part in (spec or "").split(","):
        part = part.strip()
        if not part:
            continue
        sc = _build_scorer(part)
        if sc is None:
            print(f"[shadow] 未知の scorer {part!r}。skip", file=sys.stderr)
            continue
        out.append(sc)
    return out


def maybe_run_shadow(
    articles: list[dict],
    evaluations_by_url: dict[str, dict],
    *,
    caller: str | None = None,
) -> int:
    """本番 Stage 2 の結果を受けて shadow 評価を回す。書いた件数を返す.

    ``evaluations_by_url`` は ``stage2.Stage2Result.evaluations_by_url``
    そのもの（url → ログエントリ。``美意識1`` などの日本語キーを持つ）。
    ``run_stage2`` の末尾で呼ぶので、キャッシュヒット分も層の統合後の
    最終スコアで比較できる。

    **この関数は絶対に例外を投げない。** 戻り値 0 は「何もしなかった」。
    """
    try:
        name = os.environ.get(ENV_SCORER)
        if not name:
            return 0            # 既定で無効
        scorers = []
        for sc in _build_scorers(name):
            ok, why = sc.available()
            if ok:
                scorers.append(sc)
            else:
                print(f"[shadow] {sc.name} は使えません: {why}", file=sys.stderr)
        if not scorers:
            return 0

        try:
            limit = int(os.environ.get(ENV_LIMIT) or DEFAULT_LIMIT)
        except ValueError:
            limit = DEFAULT_LIMIT

        # 本番スコアがある記事だけを対象にする（比較対象が無いと意味がない）。
        pairs = []
        for art in articles:
            url = art.get("url")
            ev = evaluations_by_url.get(url) if url else None
            if not ev:
                continue
            baseline = {jp: ev.get(jp) for _eng, jp in AESTHETIC_KEYS}
            if any(not isinstance(v, (int, float)) for v in baseline.values()):
                continue
            # C213 (2026-10-06): 層と「未採点の項目」を一緒に残す。
            #
            # layer 1 の Haiku は 3 項目しか採点せず、美意識5/6 は
            # **0 + reason="haiku_unscored"** になる。これは「Sonnet が 0 と
            # 判断した」のではなく「採点していない」。10/6 の初日データでは
            # 美意識5/6 が 62/99 件で 0 だった（うち 122 項目が haiku_unscored）。
            # Jev は代表値の都合で 1.0 未満を返せないので、この 0 と比べると
            # 相関が偽の形に引っ張られる。compare 側で除外するために印を残す。
            reasons = ev.get("evaluation_reason") or {}
            unscored = [
                jp for _eng, jp in AESTHETIC_KEYS
                if reasons.get(jp.replace("美意識", "")) == "haiku_unscored"
            ]
            meta = {
                "layer": ev.get("layer"),
                "evaluation_mode": ev.get("evaluation_mode"),
                "unscored": unscored,
            }
            pairs.append((art, baseline, meta))
            if len(pairs) >= limit:
                break
        if not pairs:
            return 0

        from . import store
        from scripts.lib.jst import jst_now_iso

        total = 0
        for scorer in scorers:
            results = scorer.score_articles([a for a, _b, _m in pairs])
            entries = []
            for (art, baseline, meta), r in zip(pairs, results):
                e = r.to_entry()
                e["baseline"] = baseline
                e["baseline_meta"] = meta
                e["caller"] = caller
                e["title"] = (art.get("title") or "")[:120]
                # C214: 入力の規模を残す。A と B の差がどこから来たかを
                # 後から説明できるようにする（本文が無ければ差は出ない）。
                try:
                    e["state_chars"] = len(scorer.build_state(art))
                except Exception:  # noqa: BLE001
                    e["state_chars"] = None
                e["recorded_at"] = jst_now_iso()
                entries.append(e)
            n = store.record(entries)
            total += n
            n_err = sum(1 for r in results if r.error)
            cost = sum(r.cost_usd for r in results)
            print(f"[shadow] {scorer.name}: {n} 件記録（失敗 {n_err}）"
                  f" caller={caller} cost=${cost:.6f}", file=sys.stderr)
            if n_err and n_err == len(results):
                print(f"[shadow] {scorer.name} 全件失敗。最初の理由: "
                      f"{results[0].error}", file=sys.stderr)
        return total
    except Exception as e:  # noqa: BLE001 — shadow は絶対に紙面を落とさない
        print(f"[shadow] 失敗 (non-fatal): {type(e).__name__}: {e}", file=sys.stderr)
        return 0
