"""ShadowScorer の抽象 (C211, 2026-10-05).

モデルを差し替えて同じ枠で測れるようにするための層。C209 の要件:

    「モデルを差し替え可能な設計にし、後で Sonnet 5.5（Batch API）も
      同じ枠で測れるようにする」

``score_articles`` は **本番と同じ 0–10 の美意識スコア**を返す契約にする。
そうすれば ``stage3.compute_final_score`` をそのまま再利用でき、
final_score の順位相関が本番と同じ式で測れる。

スコアの段階について
--------------------
本番の美意識プロンプト（``stage2.SYSTEM_PROMPT``）は各項目に
**4 つのスコアバンド**を定義している::

    9–10 / 6–8 / 3–5 / 0–2

Jev の Score 型は 2–10 段階の記述配列を取るので、**このバンド文をそのまま
criteria として渡せる**。独自の rubric を書き起こすと「Jev の性能」ではなく
「こちらの rubric の書き方」を測ってしまうため、原典をそのまま使う。

バンドから 0–10 に戻すときは **確率の期待値**を使う（C209 の論点
「確率をどう使うか」への答え）。最頻値だと 4 段階の粗さがそのまま出て
順位相関が潰れるが、期待値なら連続値になる::

    score = Σ P(band) × midpoint(band)
    midpoint: 0–2 → 1.0, 3–5 → 4.0, 6–8 → 7.0, 9–10 → 9.5

``confidence`` はスコアに混ぜず別に記録する。混ぜると相関が落ちたときに
「モデルの実力」と「confidence の重み付け」が切り分けられなくなる。
"""

from __future__ import annotations

import sys
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

# 本番 stage2 の美意識キー（stage2.AESTHETIC_KEYS と同じ並び）
AESTHETIC_KEYS: tuple[tuple[str, str], ...] = (
    ("aesthetic_1_structure_detail", "美意識1"),
    ("aesthetic_3_disciplinary_bridge", "美意識3"),
    ("aesthetic_5_otherness", "美意識5"),
    ("aesthetic_6_minority_value", "美意識6"),
    ("aesthetic_8_behavioral_economics", "美意識8"),
)

# スコアバンド → 0–10 の代表値。本番プロンプトのバンド定義に対応する。
#
# ``criteria`` は低い順に並べて渡すので、段階番号 0,1,2,3 がこの並びに対応する。
BAND_ORDER: tuple[str, ...] = ("0-2", "3-5", "6-8", "9-10")
BAND_MIDPOINTS: dict[str, float] = {
    "0-2": 1.0,
    "3-5": 4.0,
    "6-8": 7.0,
    "9-10": 9.5,
}
# 段階番号（Jev が返すキー）→ 代表値
INDEX_MIDPOINTS: tuple[float, ...] = tuple(BAND_MIDPOINTS[b] for b in BAND_ORDER)


class UnknownProbabilityKeys(ValueError):
    """``probabilities`` のキーをどの代表値にも対応づけられなかった.

    C212 (2026-10-06): **黙って 0 を返さないために例外にしている。**

    C211 の初回実装は ``probabilities`` のキーがバンド名（``"6-8"`` など）で
    返ると想定した対応表を書いた。実際の Jev は **段階番号**（``"0"``〜``"3"``、
    ``criteria`` 配列の添字）で返す。一致するキーが無いので合計が 0 になり、
    ``total <= 0`` の分岐で **0.0 を返していた**——確率は正常に返っているのに、
    スコアだけが全項目 0 になる。

    紙面には影響しないが、気づかずに 2 週間走らせたら shadow のデータが
    丸ごと無駄になる。例外にして ``ShadowScore.error`` に載せ、
    ``compare`` の失敗件数に出るようにする。
    """


def expected_score(
    probabilities: dict[str, float],
    *,
    midpoints: tuple[float, ...] = INDEX_MIDPOINTS,
) -> float:
    """バンド確率から 0–10 の期待値を出す.

    Jev は ``probabilities`` を **段階番号**で返す（``{"0": 0.51, "1": 0.17,
    "2": 0.3, "3": 0.02}``）。``criteria`` を低い順に渡しているので、
    番号がそのまま ``midpoints`` の添字になる。

    保険としてバンド名キー（``"6-8"`` など）も受け付ける。将来 API が
    表記を変えても落ちないようにするためで、現行の Jev は番号で返す。

    Raises
    ------
    UnknownProbabilityKeys
        どのキーも対応づけられなかったとき。**0.0 を返さない。**
    """
    if not probabilities:
        raise UnknownProbabilityKeys("probabilities が空")

    total = 0.0
    acc = 0.0
    unmatched: list[str] = []
    for key, p in probabilities.items():
        if not isinstance(p, (int, float)):
            unmatched.append(str(key))
            continue
        k = str(key).strip()
        mid: float | None = None
        if k.isdigit():                      # Jev の実際の形式（段階番号）
            i = int(k)
            if 0 <= i < len(midpoints):
                mid = midpoints[i]
        if mid is None:                      # 保険：バンド名
            mid = BAND_MIDPOINTS.get(_normalize_band_name(k))
        if mid is None:
            unmatched.append(k)
            continue
        total += float(p)
        acc += float(p) * mid

    if total <= 0:
        raise UnknownProbabilityKeys(
            f"どのキーも代表値に対応づけられない: keys={sorted(probabilities)} "
            f"（段階番号 0..{len(midpoints) - 1} か {sorted(BAND_MIDPOINTS)} を想定）"
        )
    if unmatched:
        # 一部だけ対応できた場合。確率の一部を捨てているので黙らない。
        print(f"[shadow] WARN: 対応づけできないキーを無視しました: {unmatched}",
              file=sys.stderr)
    return round(acc / total, 3)


def _normalize_band_name(b: str) -> str:
    return b.replace("–", "-").replace("—", "-").strip()


@dataclass
class ShadowScore:
    """1 記事ぶんの shadow 評価結果."""

    url: str
    scorer: str                       # "jev" / "sonnet-5-5" など
    scores: dict[str, float]          # 美意識キー → 0–10（期待値なので小数）
    confidence: dict[str, float] = field(default_factory=dict)
    probabilities: dict[str, dict] = field(default_factory=dict)
    # Jev が返す生の score（段階番号）。期待値と突合して写像の検算に使う。
    raw_scores: dict[str, float] = field(default_factory=dict)
    cost_usd: float = 0.0
    elapsed_ms: int = 0
    error: str | None = None

    def to_entry(self) -> dict:
        return {
            "url": self.url,
            "scorer": self.scorer,
            "scores": self.scores,
            "confidence": self.confidence,
            "probabilities": self.probabilities,
            "raw_scores": self.raw_scores,
            "cost_usd": round(self.cost_usd, 6),
            "elapsed_ms": self.elapsed_ms,
            "error": self.error,
        }


class ShadowScorer(ABC):
    """差し替え可能な shadow 評価器."""

    name: str = "base"

    @abstractmethod
    def score_articles(self, articles: list[dict]) -> list[ShadowScore]:
        """記事ごとに 0–10 の美意識スコアを返す.

        **例外を投げてはならない。** 失敗は ``ShadowScore.error`` に入れて
        返すこと。shadow が紙面を落とさないための契約。
        """

    def available(self) -> tuple[bool, str]:
        """使える状態か。``(False, 理由)`` なら runner は skip する."""
        return True, ""
