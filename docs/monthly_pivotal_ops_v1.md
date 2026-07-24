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

## §5. 月次選定における本文取得不可ソースの扱い

**方針**: bot 保護 / Vercel Security Checkpoint / HTTP 429 等により WebFetch
できないソースも、月次選定（4 記事 / 月）の候補として提示すること。fetch 不可を
理由に候補から除外してはならない。

### 5.1 なぜ除外しないか

Aeon / Psyche 等は本 profile（`news_profile.md`）の思想週に強く整合する主要
ソースであり、Sprint 11-12 の実績で継続的に主軸を供給している：

- **W5 (2026-06-21〜27)**: Aeon Essays / Katherine May 論考
- **W7 (2026-07-05〜11)**: Aeon Essays / Nicolas Berggruen 論考（15 名共同執筆）
- **W8 (2026-07-12〜18)**: Aeon Essays / Helena Miton 論考
- **W9 (2026-07-19〜25)**: Aeon Essays / Noga Arikha 論考（内受容感覚）

これらを WebFetch できないという技術的制約だけで候補から落とすと、月 4 記事の
選定プールが痩せ細り、profile 適合度の低い記事に流れざるを得なくなる。

具体的な被害事例：2026-07-24 の C150 月次選定セッションでは、Aeon / Psyche が
Vercel Security Checkpoint により全滅。W12 / W13 の候補探索が The Atlantic
と合わせて 3 サイト同時に閉じ、代替探索に時間を要した。

### 5.2 「本文 fetch 済み」と「search-only confirmed」を明示的に区別

Claude Code が主軸候補をリストアップする際、各候補に **fetch ステータス**を
必ず明記する：

| ステータス | 意味 | 神山さん側の対応 |
|---|---|---|
| **本文 fetch 済み** | WebFetch で全文取得できた候補 | そのまま選択可 |
| **search-only confirmed** | 検索結果 / 公開 metadata で存在は確認済、本文は fetch 不可 | 選択した場合は §5.3 の手動投入運用へ |

WebSearch の snippet / タイトル / 著者 / 公開日 / URL は多くの場合取得可能で、
「その記事が実在し、テーマ適合度を評価するに足る材料はある」と判断できる。
本文全文が LLM に届かないだけで、候補として提示する価値は減じない。

### 5.3 神山さんによる手動投入運用

`search-only confirmed` の候補を神山さんが選択した場合、以下のフローで
`full_text_excerpt` を投入する：

1. 神山さんがブラウザ（Chrome 等）で該当 URL を開く
   - Vercel Security Checkpoint / Cloudflare の human-verification は
     ブラウザからは通過できる（bot ではない）
2. 本文全文をコピー
3. §3.2 のクリーンアップ指針に従い、newsletter UI / 広告 / footer を除去
4. `data/monthly_pivotal.json` の該当 W エントリの `full_text_excerpt` に
   貼り付け、コミット

**実施済例**: 2026-07-19 の C147 で W9 Noga Arikha（Aeon）を神山さんが
Chrome から手動取得し、28,160 chars を投入
（[commit ad3ab2b](https://github.com/akiokamiyama-ai/kt-paper-1caa/commit/ad3ab2b)）。

### 5.4 Claude Code 側の候補提示ルール

月次選定セッション時、Claude Code は以下を遵守：

- 各候補に `[fetch: 本文取得済 / search-only]` タグを明示
- `search-only` の候補も **同格で** 提示する（末尾のおまけ扱いにしない）
- fetch 不可を理由にした暗黙の候補削除を行わない
- 各候補の fetch エラーの理由（HTTP 429 / Vercel checkpoint 等）を短く記録

これにより、「AI が fetch できない記事は選ばれない」という選定バイアスを
避け、profile 適合度を最優先の判断基準に保つ。

## §6. 関連ファイル

- 実装:
  - [`scripts/page1_v3/essay_generator.py`](../scripts/page1_v3/essay_generator.py) — essay 生成本体
  - [`scripts/page1_v3/prompts.py::format_full_text_section`](../scripts/page1_v3/prompts.py) — full_text_excerpt を prompt に埋め込む関数
  - [`scripts/page1_v3/monthly_pivotal.py`](../scripts/page1_v3/monthly_pivotal.py) — W エントリ読込
- データ:
  - [`data/monthly_pivotal.json`](../data/monthly_pivotal.json) — W1..Wn エントリ本体
- 関連観察:
  - [`docs/observations.md`](observations.md) の C126 / C143 節
