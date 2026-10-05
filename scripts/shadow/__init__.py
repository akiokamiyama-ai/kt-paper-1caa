"""Stage 2 の評価モデルを本番と並走させて比べる shadow 評価 (C209/C211).

紙面には一切影響しない:

* 本番 Stage 2（Sonnet 4.6）の結果は変えない
* ``archive/`` を書かない
* 既定で **完全に無効**。``TRIBUNE_SHADOW_SCORER`` が設定されたときだけ動く
* 呼び出し全体が try/except で囲まれており、shadow が落ちても紙面は出る
  （C201 の「通知は best-effort、起動は必達」と同じ原則）

モジュール:
    base    ShadowScorer の抽象と ShadowScore
    jev     TypeSafe AI の Jev（判断専用モデル）
    store   logs/shadow_eval_<date>.json の読み書き（同一日は upsert）
    compare 相関の計算
"""
