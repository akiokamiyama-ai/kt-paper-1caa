# Business — グローバル経済・経営論考の情報源

このファイルは Kamiyama Tribune の本紙ベース情報源リストである。
第1面（The Front Page）と第3面（General News）に流れる **グローバル経済・国内ビジネス・経営論考** を扱うソースを、**ウォッチ優先順位（高 / 中 / 低）×ソース** のマトリクスで記録する。

国際情勢・地政学に特化したソース（Foreign Affairs、Foresight、Brookings 等）は `sources/geopolitics.md` を参照。3社事業文脈は `sources/companies.md` を参照。

選定の方針は `news_profile.md` §4.1 を参照。Tribune全体の選定基準は同文書 §3 の美意識7項目と §5 の横断ルール。特に「**行動経済学的視点をビジネス記事の選定フィルタとして組み込む**」「**主流外の本質的論者を発掘する**」「特定起業家への崇敬と表面的な成功談は弾く」を強く意識すること。

**ステータス凡例**：
- ✅ 検証済み（フィード/URLが実際に取得できることを確認）
- ⚠️ 一部未検証（URLは到達するが、フィード形式・更新頻度・カテゴリ分けは要追加調査、または公式RSS不在で代替手段で運用）
- ❌ 未検証（時間切れ、または取得エラー。次回セッションで再調査）

---

## High Priority（毎日チェック）

### 1. 日本経済新聞（電子版） ⚠️
- **URL**: https://www.nikkei.com/
- **RSS**: 公式RSSは廃止（`/rss/`、`/news/feed/`、`/rss/index.rdf` 全て404）。**サードパーティミラー** `assets.wor.jp` 経由で稼働（RDF 形式、検証時に最新18件取得確認）。`world.rdf`/`politics.rdf` は 403。**2026-04 以降ブラウザUA必須**（site_overrides.toml に登録済）
  - https://assets.wor.jp/rss/rdf/nikkei/business.rdf
  - https://assets.wor.jp/rss/rdf/nikkei/economy.rdf
  - https://assets.wor.jp/rss/rdf/nikkei/international.rdf
  - https://assets.wor.jp/rss/rdf/nikkei/sports.rdf
- **形式**: RSS 1.0 (RDF)（ミラー経由）
- **mainstream**: true
- **対象**: 国内ビジネス・経済・国際ニュース全般。本紙の国内軸の中核
- **位置付け**: **本紙第1面・第3面の国内軸の中核**。日経電子版本体は有料記事多数だが、**見出し・冒頭3〜4文は無料表示**されるため、見出し+リード文の取得で十分多くのケースに対応できる。ミラー経由のため Nikkei が静止画認証を強化すると破綻リスクあり、フェーズ1で日経本体の Atom 配信再開有無を継続監視

> **2026-05-04 状況メモ**：RSS（assets.wor.jp ミラー）の `<description>` は全 item で空文字列。Stage 1 description_length filter (30字未満) ですべて弾かれる。**これは現状維持**（神山さんが有料購読中のため Tribune で再露出する価値が低い、意図的に exempt list に入れない）。将来 RSS 仕様変更で description が復活した場合、自動的に Tribune 候補に復帰する。

### 2. NHK ニュース 経済 ✅
- **URL**: https://www3.nhk.or.jp/news/news_keizai.html
- **RSS**: https://www3.nhk.or.jp/rss/news/cat5.xml
- **形式**: RSS 2.0（default UA で 200、UA override 不要）
- **mainstream**: true
- **対象**: 国内経済・産業・為替・物価・主要企業ニュース。政府発表 / 公的データ中心の硬派なカバレッジ
- **位置付け**: **第3面 R2「国内マクロ・産業」の主力ソース**。日経電子版が title-only feed のため Stage 1 で全弾きされる中、本ソースが事実上の代替。description が全 item に 65-130 字あり Stage 1 通過率 100%。日次 18 本ペースで R2 を安定供給する。NHK 独立した編集視点 + 信頼性 = 神山さんの経営者視点と整合。Sprint 5 task #1 (2026-05-04) で High Priority に採用

### 3. The Economist ✅
- **URL**: https://www.economist.com/
- **RSS**: セクション別RSS稼働中
  - Finance and Economics: https://www.economist.com/finance-and-economics/rss.xml
  - Business: https://www.economist.com/business/rss.xml
  - Leaders（社説）: https://www.economist.com/leaders/rss.xml
  - Briefing（深掘り解説）: https://www.economist.com/briefing/rss.xml
  - Science and Technology: https://www.economist.com/science-and-technology/rss.xml
- **language**: en
- **形式**: RSS 2.0
- **mainstream**: true
- **対象**: グローバル経済・金融・ビジネス・科学技術の論考。英語原文
- **位置付け**: **グローバル分析・論考の最重要ソース**。news_profile.md §4.1 の「経営判断の合理性の限界」「構造と細部の往復」と最も親和性が高い。Leaders と Briefing は **構造的・長期視点**（§4.3）の記事の宝庫。本紙では「英語原文のまま採用」を基本方針（§5 編集ポリシー）

### 4. BBC Business（本紙第1面で稼働中） ✅
- **URL**: https://www.bbc.com/business
- **RSS**: https://feeds.bbci.co.uk/news/business/rss.xml
- **language**: en
- **形式**: RSS 2.0
- **mainstream**: true
- **対象**: グローバル経済・企業・市場の速報＋分析（英国視点が強め）
- **位置付け**: **既に `experiment/regen_front_page.py` 経由で第1面のライブ動的生成に組み込み済み**。フェーズ1で `scripts/fetch.py` にリファクタリングする際もこのフィードを継続採用。BBC は CSS 命名規則変更で本文抽出が破綻しうる点が既知の脆さ（roadmap.md §4.2）

### 5. Reuters Business ⚠️
- **URL**: https://www.reuters.com/business/
- **RSS**: **公式RSSは2020年以降廃止**（旧 `/arc/outboundfeeds/` 系も404、`reutersagency.com/feed/` も最新フィード非公開）。代替として **Google News RSS プロキシ** `https://news.google.com/rss/search?q=site:reuters.com+business&hl=en-US&gl=US&ceid=US:en` で間接取得可（200確認、最新エントリ含む）
- **language**: en
- **形式**: RSS 2.0（Google News 経由）
- **mainstream**: false
- **対象**: グローバル経済・市場・企業の速報、事実関係に強い
- **位置付け**: **速報軸**として The Economist（論考軸）と相補的に運用。news_profile.md §4.3 では「速報より深さ」の方針だが、Reuters の事実関係は他ソース記事の **裏取り** として有用。Google News プロキシ運用のリスク（Google 側 API 仕様変更）をフェーズ1で評価

---

## Medium Priority（候補が薄い日に拾う）

### 6. McKinsey Insights ✅
- **URL**: https://www.mckinsey.com/insights
- **RSS**: https://www.mckinsey.com/insights/rss
- **language**: en
- **形式**: RSS 2.0（Sitecore 配信、検証時に最新記事「From promise to impact: How companies can measure—and realize—the full value of AI」を取得確認）
- **mainstream**: false
- **対象**: 経営戦略、デジタル・AI、組織、リーダーシップ、産業別分析（QuantumBlack の AI 特化記事も含む）
- **位置付け**: **戦略コンサルの代表的論考ソース**。news_profile.md §4.1 の経営思想系（楠木建・三品和広・遠藤功）と並走させて、**実務側の視点** を補強する。AI実装の経営インパクトを扱う記事は Cocolomi 事業文脈（`companies.md`）とも横断する

### 7. BCG Insights / Henderson Institute ❌
- **URL**: https://www.bcg.com/about/insights / https://bcghendersoninstitute.com/
- **RSS**: **未提供**（HTML上に明示なし）。`feed.xml`、`/publications/rss`、sitemap.xml すべて Akamai が 403 で遮断。WebFetch も 403
- **language**: en
- **形式**: ❌ プログラマティック取得不可
- **mainstream**: false
- **対象**: 経営戦略、企業文化、長期トレンド分析、産業別レポート
- **位置付け**: コンテンツの質は McKinsey と並ぶが、**配信インフラが完全に閉じている**。フェーズ1では断念。代替として **Strategy+Business**（PwC、下記7番）と McKinsey で経営コンサル系論考をカバーする方針。BCG の重要レポートは Twitter/LinkedIn 経由で察知して個別 URL を手動取得する運用を検討

### 8. Bloomberg Opinion ⚠️
- **URL**: https://www.bloomberg.com/opinion
- **RSS**: **Opinion 単独フィードは公式廃止**（`/opinion.rss`、`/opinion/news.rss`、`/bview/opinion.rss` 全て404）。代替として近接フィード稼働中：
  - https://feeds.bloomberg.com/markets/news.rss（市場ニュース＋一部Opinion混在、200確認）
  - https://feeds.bloomberg.com/wealth/news.rss（200確認）
  - https://feeds.bloomberg.com/politics/news.rss（200確認）
- **language**: en
- **形式**: RSS 2.0
- **mainstream**: false
- **対象**: マーケット解説、コラム、政治経済論考
- **位置付け**: 本紙が望むのは **コラム・論考軸**（速報軸は Reuters・BBC でカバー済）。markets フィードから `byline` や記事URLパス `/opinion/` でフィルタする運用を想定。フェーズ1で Opinion 抽出ロジックを検討、効果が薄ければ優先度を Reference に下げる

### 9. 東洋経済オンライン ✅
- **URL**: https://toyokeizai.net/
- **RSS**: https://toyokeizai.net/list/feed/rss
- **形式**: RSS 2.0
- **mainstream**: false
- **対象**: ビジネス全般、業界分析、企業経営、政策論考
- **位置付け**: **`companies.md` でも参照** されている共通ソース（Web-Repo の Reference）。本紙では国内ビジネス論考のサブとして運用。日経が見出ししか取れない場合の **本文付きの代替** として価値が高い。重複排除ロジック（`logs/urls_*.json`）で `companies.md` 側との二重採用を防ぐ

### 10. 朝日新聞デジタル 経済 ⚠️
- **URL**: https://www.asahi.com/business/
- **RSS**: https://www.asahi.com/rss/asahi/business.rdf
- **形式**: RSS 1.0 (RDF)、default UA で 200
- **mainstream**: true
- **対象**: 国内マクロ・産業、社会観察視点の経済記事。政府発表 / 企業ニュース / 国際エネルギー / 消費者問題 / 当事者取材記事
- **位置付け**: **第3面 R2「国内マクロ・産業」の補完ソース**。NHK と編集視点が補完的（高島屋の視覚障害者向け売り場、上場企業金塊マネー等の独自切り口は NHK では拾われない領域）。Sprint 5 task #1 (2026-05-04) で Medium Priority に採用、7-14 日運用観察で R2 充足率改善を確認後 High 昇格を検討
- **注意**：RSS の `<description>` は全 item で空文字列（title-only feed）。Stage 1 description_length filter (30字未満) ですべて弾かれるため、`config/site_overrides.toml` の `description_exempt = true` で **www.asahi.com を exempt list に登録**。Stage 2 LLM 評価は title 重視で行う設計（`stage2.py` の prompt で title-only feed の評価指示を明示）

### 11. WIRED.com Backchannel ✅
- **URL**: https://www.wired.com/category/backchannel/
- **RSS**: https://www.wired.com/feed/category/backchannel/latest/rss
- **language**: en
- **形式**: RSS 2.0（**ブラウザUAが必要**、デフォルトUAでは 403。`config/site_overrides.toml` で `www.wired.com` に Chrome UA を設定済）
- **mainstream**: true
- **対象**: テック × 社会の長文ジャーナリズム。Apple / OpenAI / Tesla / 政府機関の深い取材記事、業界人物ルポ、検証記事
- **位置付け**: 神山さんの「**AI関連、テック関連をビジネスとして読んで、学びにしたい**」要請への直接対応。Backchannel は WIRED の長文枠で、**業界の構造変化を物語の形で読める**。McKinsey/HBR/Strategy+Business が「経営論考」、WIRED Backchannel は「**当事者ルポ**」という相補配置。**更新頻度は週1〜2本（2026-05-03 計測：直近5本の平均間隔 ≈4日）**

### 12. WIRED.com AI ✅
- **URL**: https://www.wired.com/tag/ai/
- **RSS**: https://www.wired.com/feed/tag/ai/latest/rss
- **language**: en
- **形式**: RSS 2.0（**ブラウザUAが必要**、`www.wired.com` UA override に依存）
- **mainstream**: true
- **対象**: AI 業界動向、規制、企業戦略、AI 倫理、当局報道。OpenAI / Anthropic / Google / Meta / Microsoft の動き、AI Act / EU AI 規制等
- **位置付け**: 神山さんの **AI 推進機構監査役** としての情報収集に直結。日次 1〜2 本の安定供給で、Backchannel と組み合わせて WIRED.com からの AI 関連カバレッジを完結させる。**更新頻度は1日1〜2本（2026-05-03 計測：直近5本が48時間以内）**

---

## Reference（月1の俯瞰用）

### 13. Strategy+Business（PwC） ✅
- **URL**: https://www.strategy-business.com/
- **RSS**: https://www.strategy-business.com/rss
- **language**: en
- **形式**: RSS（HTML内 `href="https://www.strategy-business.com/rss"` で発見、200確認）
- **mainstream**: false
- **対象**: 経営戦略、リーダーシップ、組織、テクノロジー戦略（PwC 系列の経営思想誌）
- **位置付け**: **BCG が取れない穴を埋める** PwC 系経営思想ソース。McKinsey Insights が「コンサル現場の論考」とすれば、Strategy+Business は **アカデミックと実務の中間**。月1俯瞰で十分だが、特集号が出た月は High 扱いに引き上げる

### 14. Behavioral Scientist ✅
- **URL**: https://behavioralscientist.org/
- **RSS**: https://behavioralscientist.org/feed/
- **language**: en
- **形式**: RSS 2.0（検証時 371KB の本文付きフィード、LiteSpeed 配信）
- **mainstream**: false
- **対象**: 行動経済学、認知バイアス、意思決定科学、ナッジ理論、応用心理学
- **位置付け**: **news_profile.md §4.1 の特記要件**「行動経済学的視点をビジネス記事の選定フィルタとして組み込む」の **直接的な情報源**。カーネマン、セイラー、アリエリー、チャルディーニ系の論考が中心。本文丸ごと配信のため、本紙取り込み時の追加スクレイピング不要

### 15. NBER Working Papers ✅
- **URL**: https://www.nber.org/papers
- **RSS**: https://back.nber.org/rss/new.xml（旧 `www.nber.org/rss/new.xml` は 301、新ドメイン `back.nber.org` で配信）
- **language**: en
- **形式**: RSS（Apache/2.4.66 + mod_perl 配信、40KB）
- **mainstream**: false
- **対象**: 経済学一次情報（労働経済学、マクロ、行動経済学、産業組織論、教育経済学等）。世界中の経済学者の Working Paper
- **位置付け**: **学術一次情報** として、Aeon（`companies.md` Reference）と並ぶ深掘り枠。news_profile.md §4.4「学術領域」とも重なる。週数十本のペースで新着があるためノイズ多め、行動経済学・産業政策系のみアブストラクトベースでフィルタする運用を想定

---

## 一次情報URL（参考メモ）

調査過程で収集した、RSS/メタデータ整備の手がかりとなる一次情報URL：

- **日経 wor.jp ミラー全カテゴリ一覧**: https://assets.wor.jp/rss/rdf/nikkei/ （ディレクトリリスティング不可だが `business/economy/international/sports.rdf` は確認済、`world/politics.rdf` は 403）
- **The Economist 全RSS一覧**: https://www.economist.com/rss （セクション別RSSのインデックス）
- **Reuters Agency 公式（旧）**: https://www.reutersagency.com/en/coverage/ （RSS は終了、ニュース配信API は要契約）
- **Bloomberg 全フィード一覧**: https://feeds.bloomberg.com/ （markets/wealth/politics/technology 等のサブカテゴリ）
- **McKinsey RSS インデックス**: McKinsey は `/insights/rss` 一本のみ。テーマ別RSSは未提供
- **NBER Pantheon ホスティング**: `back.nber.org` は Pantheon 経由配信。`nb-sec-nber.pantheonsite.io` がCSP上のスクリプト配信元

---

## 次回セッションのTODO

優先度順：

1. **日経 wor.jp ミラーの永続性評価**（フェーズ1） — `assets.wor.jp` は個人運営の可能性。**1ヶ月のフィード更新監視**を仕込み、停止時のフォールバック（Yahoo!ニュース ビジネスRSS、News24 等）を準備
2. **Reuters Google News プロキシの仕様安定性検証** — Google News RSS は仕様変更が多い。フェーズ1で 1〜2週間運用してエントリ取得頻度・遅延を測定
3. **Bloomberg Opinion 抽出ロジック設計**（フェーズ2） — markets フィードから `/opinion/` パスや署名でフィルタする実装。効果が薄ければ Bloomberg を Reference 落ち
4. **BCG 代替ルートの検討** — フェーズ1では断念したが、BCG レポートの本紙価値が高ければ **手動URL登録ワークフロー**（Slack/メールで届いた URL を `sources/manual_urls.md` に追記）を検討
5. **The Economist セクションの優先度設計** — 5セクション全採用は記事過多。**Leaders + Briefing を High、Finance/Business を Medium、Science を低頻度** とする運用ルール案を `news_profile.md` §4.1 にフィードバック
6. **重複排除ロジック**（特に McKinsey ↔ Strategy+Business のテーマ重複、東洋経済 ↔ companies.md 側）
7. **行動経済学キーワードリストの整備** — Behavioral Scientist のフィルタとは別に、**他ソース全体に対する「行動経済学スコア」** をキーワードベースで付与する設計（フェーズ2、`news_profile.md` §4.1 を反映）

---

**文書バージョン**：v0.1
**作成日**：2026/4/27（火曜夜セッション）
**更新履歴**：
- v0.1（2026/4/27）：初版作成、11ソース整備（✅7件、⚠️3件、❌1件）。BCG は Akamai 完全遮断のためフェーズ1断念、Strategy+Business で代替。Reuters/Bloomberg Opinion の公式RSS消失を確認、それぞれ Google News プロキシ・近接フィードで代替

**次回見直し**：`sources/geopolitics.md` 作成完了時、または `fetch.py` 設計時
