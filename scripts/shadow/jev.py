"""TypeSafe AI の Jev で美意識を採点する shadow 評価器 (C211, 2026-10-05).

Jev は自由記述を返さず、事前に定義した質問に対して**型付きの答えと確率**を
返す「判断専用（System One）」モデル。Stage 2 の美意識採点は本質的に
「選択肢に点を付ける」仕事なので形が合う。

API（docs.typesafe.ai で確認、2026-10-05）::

    POST https://api.typesafe.ai/v1/systemone
    Authorization: Bearer <API_KEY>

    {"state": <記事>, "model": "jev-latest",
     "questions": {"<名前>": {"type": "score",
                              "instructions": "...",
                              "criteria": ["<バンド記述>", ...]}}}

    → {"model": ..., "usage": {"input_tokens", "output_tokens"},
       "answers": {"<名前>": {"type": "score", "score": n,
                              "legend": {...}, "probabilities": {...},
                              "confidence": 0–1}}}

質問は 1 リクエストで並列評価されるので、美意識 5 項目を 1 回で投げる。

rubric は原典から読む
---------------------
``criteria`` は ``stage2.SYSTEM_PROMPT`` の美意識バンド定義を**実行時に
パースして**使う。ここに書き写すと C197（事業定義が 2 箇所にあってずれた）と
同じことが起きる。本番プロンプトを編集したら shadow も自動で追従する。

未確認事項（2026-10-05 時点）
-----------------------------
公式ドキュメントに記載が無く、実際に叩くまで分からないもの:

* **日本語入力の可否**（言語サポートの記述が無い）
* 入力長の上限
* レート制限の具体値（429 / 529 を返すこと、exponential backoff 推奨のみ）

このため本モジュールは **API キーが設定されるまで一切動かない**
（``available()`` が False を返す）。日本語が通らなければ設計の前提が崩れるので、
まず ``--probe`` で 1 本だけ投げて確認すること。
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

from .base import AESTHETIC_KEYS, BAND_ORDER, ShadowScore, ShadowScorer, expected_score

API_URL = "https://api.typesafe.ai/v1/systemone"
API_KEY_ENV = "TYPESAFE_API_KEY"
DEFAULT_MODEL = "jev-latest"

# 料金（2026-10-05 確認）: 入力 $0.042/1M、出力無料。
INPUT_PER_MTOK = 0.042
OUTPUT_PER_MTOK = 0.0

# 記事本文をこの長さで切る。入力長の上限が未公開なので保守的に。
BODY_LIMIT = 2000

_BAND_RE = re.compile(r"^-\s*(\d+[–-]\d+)\s*[：:]\s*(.+)$", re.M)
_SECTION_RE = re.compile(r"\n### 美意識(\d)[：:]")


def _normalize_band(b: str) -> str:
    """``"9–10"``（en dash）→ ``"9-10"``."""
    return b.replace("–", "-").replace("—", "-").strip()


def build_criteria() -> dict[str, dict]:
    """本番プロンプトから美意識ごとの説明とバンド記述を抜く.

    Returns ``{"美意識1": {"instructions": str, "bands": {band: desc}}, ...}``
    """
    from scripts.selector import stage2

    parts = _SECTION_RE.split(stage2.SYSTEM_PROMPT)
    out: dict[str, dict] = {}
    for num, body in zip(parts[1::2], parts[2::2]):
        bands = {
            _normalize_band(b): d.strip()
            for b, d in _BAND_RE.findall(body)
        }
        if not bands:
            continue
        # バンド一覧より前の地の文が、その項目の評価軸の説明。
        head = body.split("スコアバンド")[0]
        head = re.sub(r"^\s*（重み\d+）\s*", "", head).strip()
        # 見出し行の残り（「構造と細部の往復（重み18）」）を落として本文だけ使う
        lines = [l.strip() for l in head.splitlines() if l.strip()]
        instructions = " ".join(lines[1:]) if len(lines) > 1 else " ".join(lines)
        out[f"美意識{num}"] = {"instructions": instructions, "bands": bands}
    return out


class JevScorer(ShadowScorer):
    name = "jev"

    def __init__(self, *, api_key: str | None = None, model: str = DEFAULT_MODEL,
                 timeout: float = 30.0, url: str = API_URL):
        self.api_key = api_key or os.environ.get(API_KEY_ENV)
        self.model = model
        self.timeout = timeout
        self.url = url
        self._criteria = None

    # -- 可用性 ------------------------------------------------------------
    def available(self) -> tuple[bool, str]:
        if not self.api_key:
            return False, f"{API_KEY_ENV} が未設定（console.typesafe.ai/keys で発行）"
        try:
            c = self.criteria()
        except Exception as e:  # noqa: BLE001
            return False, f"美意識バンドのパースに失敗: {type(e).__name__}: {e}"
        missing = [jp for _, jp in AESTHETIC_KEYS if jp not in c]
        if missing:
            return False, f"本番プロンプトからバンドが取れない項目: {missing}"
        return True, ""

    def criteria(self) -> dict[str, dict]:
        if self._criteria is None:
            self._criteria = build_criteria()
        return self._criteria

    # -- リクエスト組み立て ------------------------------------------------
    def build_questions(self) -> dict[str, dict]:
        """美意識 5 項目を Jev の score 質問に落とす（バンドは原典のまま）."""
        c = self.criteria()
        questions: dict[str, dict] = {}
        for eng, jp in AESTHETIC_KEYS:
            spec = c[jp]
            # criteria は「低い順」に並べる（BAND_ORDER が 0-2 → 9-10）。
            levels = [f"{b}: {spec['bands'][b]}" for b in BAND_ORDER if b in spec["bands"]]
            questions[eng] = {
                "type": "score",
                "instructions": spec["instructions"],
                "criteria": levels,
            }
        return questions

    @staticmethod
    def build_state(article: dict) -> dict:
        body = (article.get("body") or "").strip()
        return {
            "title": (article.get("title") or "").strip(),
            "source": (article.get("source_name") or "").strip(),
            "description": (article.get("description") or "").strip(),
            "body": body[:BODY_LIMIT],
        }

    def _post(self, payload: dict) -> dict:
        req = urllib.request.Request(
            self.url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            return json.loads(r.read().decode("utf-8"))

    # -- 本体 --------------------------------------------------------------
    def score_articles(self, articles: list[dict]) -> list[ShadowScore]:
        """記事ごとに 1 リクエスト。**例外は投げず error に入れて返す。**"""
        questions = None
        out: list[ShadowScore] = []
        for art in articles:
            url = art.get("url") or ""
            started = time.monotonic()
            try:
                if questions is None:
                    questions = self.build_questions()
                resp = self._post({
                    "state": self.build_state(art),
                    "model": self.model,
                    "questions": questions,
                })
                scores: dict[str, float] = {}
                conf: dict[str, float] = {}
                probs: dict[str, dict] = {}
                for eng, _jp in AESTHETIC_KEYS:
                    a = (resp.get("answers") or {}).get(eng) or {}
                    p = {_normalize_band(k): v for k, v in (a.get("probabilities") or {}).items()}
                    probs[eng] = p
                    # 期待値を使う。最頻値だと 4 段階の粗さが順位相関を潰す。
                    scores[eng] = expected_score(p) if p else float(a.get("score") or 0)
                    if isinstance(a.get("confidence"), (int, float)):
                        conf[eng] = float(a["confidence"])
                u = resp.get("usage") or {}
                cost = (int(u.get("input_tokens") or 0) / 1e6 * INPUT_PER_MTOK
                        + int(u.get("output_tokens") or 0) / 1e6 * OUTPUT_PER_MTOK)
                out.append(ShadowScore(
                    url=url, scorer=self.name, scores=scores, confidence=conf,
                    probabilities=probs, cost_usd=cost,
                    elapsed_ms=int((time.monotonic() - started) * 1000),
                ))
            except urllib.error.HTTPError as e:
                body = ""
                try:
                    body = e.read().decode("utf-8", "replace")[:200]
                except Exception:  # noqa: BLE001
                    pass
                out.append(ShadowScore(
                    url=url, scorer=self.name, scores={},
                    elapsed_ms=int((time.monotonic() - started) * 1000),
                    error=f"HTTP {e.code}: {body}",
                ))
            except Exception as e:  # noqa: BLE001 — shadow は絶対に投げない
                out.append(ShadowScore(
                    url=url, scorer=self.name, scores={},
                    elapsed_ms=int((time.monotonic() - started) * 1000),
                    error=f"{type(e).__name__}: {e}",
                ))
        return out


# ---------------------------------------------------------------------------
# 疎通確認（--probe）
# ---------------------------------------------------------------------------

def _probe() -> int:
    """日本語 1 本を実際に投げて、通るかだけ確認する.

    2026-10-05 時点で Jev の公式ドキュメントに**言語サポートの記述が無い**。
    Tribune は記事タイトル・本文が日本語なので、ここが通らなければ設計の
    前提が崩れる。本番に入れる前に必ずこれで確かめること。

    使い方::

        TYPESAFE_API_KEY=... python3 -m scripts.shadow.jev --probe
    """
    s = JevScorer()
    ok, why = s.available()
    if not ok:
        print(f"NG: {why}", file=sys.stderr)
        return 1
    art = {
        "url": "https://probe.local/1",
        "title": "暗黙知はなぜ言語化できないのか——ポランニーの再読",
        "source_name": "疎通確認",
        "description": (
            "熟練した職人が指先で素材の状態を読むとき、その知識はマニュアルにも"
            "報告書にも収まらない。マイケル・ポランニーの「語れる以上のことを"
            "知っている」という洞察を、現象学と経営学の双方から読み直す。"
        ),
        "body": "",
    }
    print(f"POST {s.url}  model={s.model}")
    print(f"質問 5 本（美意識 1/3/5/6/8、各 4 段階）、state は日本語\n")
    [r] = s.score_articles([art])
    if r.error:
        print(f"NG: {r.error}", file=sys.stderr)
        print("\n→ 日本語が原因かを切り分けるため、同じ state を英語にして"
              "再試行してください。", file=sys.stderr)
        return 1
    print("OK: 日本語の state が通りました")
    for eng, jp in AESTHETIC_KEYS:
        print(f"  {jp}  score={r.scores.get(eng)}  "
              f"confidence={r.confidence.get(eng)}  "
              f"probabilities={r.probabilities.get(eng)}")
    print(f"\n  コスト ${r.cost_usd:.8f} / レイテンシ {r.elapsed_ms} ms")
    return 0


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="Jev の疎通確認")
    ap.add_argument("--probe", action="store_true",
                    help="日本語 1 本を実際に投げて通るか確認する")
    a = ap.parse_args()
    if a.probe:
        sys.exit(_probe())
    ap.print_help()
    sys.exit(0)
