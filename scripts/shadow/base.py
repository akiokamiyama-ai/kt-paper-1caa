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
BAND_MIDPOINTS: dict[str, float] = {
    "0-2": 1.0,
    "3-5": 4.0,
    "6-8": 7.0,
    "9-10": 9.5,
}
BAND_ORDER: tuple[str, ...] = ("0-2", "3-5", "6-8", "9-10")


def expected_score(probabilities: dict[str, float]) -> float:
    """バンド確率から 0–10 の期待値を出す.

    ``probabilities`` のキーはバンド名（``"6-8"`` など）。未知のキーは無視する。
    確率の合計が 1 でなければ正規化する（API 側の丸めへの保険）。
    """
    total = 0.0
    acc = 0.0
    for band, p in (probabilities or {}).items():
        mid = BAND_MIDPOINTS.get(str(band).strip())
        if mid is None or not isinstance(p, (int, float)):
            continue
        total += float(p)
        acc += float(p) * mid
    if total <= 0:
        return 0.0
    return round(acc / total, 3)


@dataclass
class ShadowScore:
    """1 記事ぶんの shadow 評価結果."""

    url: str
    scorer: str                       # "jev" / "sonnet-5-5" など
    scores: dict[str, float]          # 美意識キー → 0–10（期待値なので小数）
    confidence: dict[str, float] = field(default_factory=dict)
    probabilities: dict[str, dict] = field(default_factory=dict)
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
