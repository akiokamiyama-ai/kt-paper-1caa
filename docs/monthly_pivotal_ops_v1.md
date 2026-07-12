# Monthly Pivotal 運用ルール v1

**作成日**: 2026-07-13（C143）
**対象**: `data/monthly_pivotal.json` の週次エントリと Page I 論考 (page1_v3) の運用

## このドキュメントの目的

Page I (Phase 3 / 2026-05-23 切替) は「1 週間、同じ主軸記事を異なる角度から
読み解く」設計で、`data/monthly_pivotal.json` の W エントリを 7 日間参照
する。運用時に守るべき情報供給ルールを明文化する。

## §1. 原則: 主軸記事の本文は必ず LLM に与える

**主軸記事の**本文（full article text）**を `full_text_excerpt` フィールドに
必ず投入する**。要約や title のみで essay 生成させることは、以下の理由で
**不可**とする。

### 1.1 なぜ本文が必要か（実証例）

- **W7 (7/5-11, Berggruen 論考)**: `full_text_excerpt` = 8,440 chars 投入済。
  Day 5「歴史」essay は 15 名の哲学者の共同執筆という記事の実相を正確に
  引用でき、藤原惺窩・林羅山までの日本受容史との具体的接続が可能だった
- **W8 (7/12-18, Miton 論考)**: Day 1 (7/12 朝刊) は投入前で summary のみ。
  essay は Polanyi の暗黙知の一般論に流れ、Miton 固有の「ビットのネット
  ワーク」「degrees of freedom の削減」「Fosbury Flop」等の具体例を
  引用できなかった。7/12 昼に手動投入 (`f81958d`) → Day 2 (7/13 朝刊、
  critical 角度) では本文の具体的引用が復活、品質が明確に上がった

### 1.2 情報供給の技術的実態

`scripts/page1_v3/essay_generator.py::_build_user_message` 経由で、
[prompts.py::format_full_text_section](../scripts/page1_v3/prompts.py) が
以下のように動作する:

```python
def format_full_text_section(full_text_excerpt: str) -> str:
    if not full_text_excerpt or not full_text_excerpt.strip():
        return ""  # ← セクション自体が prompt に現れない (fail-silent)
    return (
        "\n【原文抜粋（主要段落、summary / points で拾いきれない具体思想を LLM に届ける）】\n"
        f"{full_text_excerpt.strip()}\n"
    )
```

`full_text_excerpt` が空/欠落だと LLM は summary + key_quote + points のみで
essay を書く。要約から具体的な語彙・論拠・実例を再構成させると、LLM の
一般的知識で埋めた"それっぽい"論述になり、W テーマの独自性が失われる。

## §2. 現状のカバー範囲（本文が届いている曜日）

Days 1-6（日〜金）の 6 angles は全て `essay_generator._build_user_message`
経由で本文供給される。

| 曜日 | angle_key | 本文供給 |
|---|---|---|
| 日 | overview | ✓ (`full_text_excerpt` が入っていれば) |
| 月 | critical | ✓ |
| 火 | practitioner | ✓ |
| 水 | thinker | ✓ |
| 木 | history | ✓ |
| 金 | integration | ✓ |
| 土 | (response) | ✗（対象外、下記 §3 参照） |

### 2.1 例外: 土曜 (Day 7 saturday_responder)

土曜は「神山さんコメント → AIかみやま 応答」の別経路
(`scripts/page1_v3/saturday_responder.py`) で、Sonnet 論考生成ではなく
miibo agent への utterance 送信。この経路は `full_text_excerpt` を
参照しない設計で、それが妥当（応答はコメント自体に対する反応であり、
主軸記事本文の再引用は不要）。

## §3. 投入運用（神山さん手動オペレーション）

現状 `full_text_excerpt` は Aeon / Foreign Affairs 等の外部サイトから
神山さんが手動でコピペ投入する運用。

### 3.1 投入タイミング

**W エントリ確定時、Day 1（日曜）朝 cron の前まで**に本文を投入する。
Day 1 の essay が生成された後に投入すると Day 1 の品質が保てないため、
月次選定サイクル（7/25 頃の W10-W13 選定など）と同期させる。

### 3.2 クリーンアップ指針

原文をコピペする際、以下の要素は excerpt に含めない:

- Newsletter 登録 UI / メール登録フォーム
- 広告 / ソーシャルシェアボタン
- 動画埋め込みマーカー（YouTube タイトルのみの独立行など）
- 画像キャプション（本文と重複する場合）
- サイト footer（"Published in association with..." など）
- タグリスト / 分類ラベル

参考実装: C126 W7 投入 (8,440 chars) / C143 W8 投入 (20,658 chars)
（[commit f81958d](https://github.com/akiokamiyama-ai/kt-paper-1caa/commit/f81958d)）

### 3.3 目安のサイズ

W7: 8,440 chars / W8: 20,658 chars。Sonnet 4.6 の context window は十分
広い（200k tokens ≈ 400k chars 相当）ため、記事本文サイズはボトルネック
にならない。長い論考でも全文投入して良い。

## §4. 未投入検知（今後の課題）

現在は「投入し忘れ」の検知機構がない。essay 生成時に
`full_text_excerpt` が空でも警告が出ない。将来的な改善余地:

- `essay_generator._build_user_message` に警告ログを追加（空の場合
  `[page1_v3] WARN: W{n} full_text_excerpt is empty, essay quality
  degraded` を stderr）
- 週次 cron で `data/monthly_pivotal.json` を検査し、当週の
  `full_text_excerpt` が空なら Slack / メール通知
- 月次選定時のチェックリストに「full_text_excerpt 投入」を明示

現状は本ドキュメント自体が checklist の役割を担う。

## §5. 関連ファイル

- 実装:
  - [`scripts/page1_v3/essay_generator.py`](../scripts/page1_v3/essay_generator.py) — essay 生成本体
  - [`scripts/page1_v3/prompts.py::format_full_text_section`](../scripts/page1_v3/prompts.py) — full_text_excerpt を prompt に埋め込む関数
  - [`scripts/page1_v3/monthly_pivotal.py`](../scripts/page1_v3/monthly_pivotal.py) — W エントリ読込
- データ:
  - [`data/monthly_pivotal.json`](../data/monthly_pivotal.json) — W1..Wn エントリ本体
- 関連観察:
  - [`docs/observations.md`](observations.md) の C126 / C143 節
