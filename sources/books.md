# Books — 読書領域の情報源

このファイルは Kamiyama Tribune **第5面 Leisure 読書枠** の情報源リストである。
読書プロファイルの4サブカテゴリ（**日本の小説 / 海外純文学 / SF / 自然科学ノンフィクション**）ごとに、ソースを **ウォッチ優先順位（高 / 中 / 低）×ソース** のマトリクスで記録する。

選定の方針は `news_profile.md` §4.5 を参照。Tribune全体の選定基準は同文書 §3 の美意識7項目と §5 の横断ルール。特に「**主流外の本質的な作家・作品を発掘する**」「**ジャンルで作家を区別せず作品単位で読む**」「**ロマンス中心・ライトノベル系は弾く**」を強く意識すること。

**ステータス凡例**：
- ✅ 検証済み（フィード/URLが実際に取得できることを確認）
- ⚠️ 一部未検証（URLは到達するが、フィード形式・更新頻度・カテゴリ分けは要追加調査、または公式RSS不在で代替手段で運用）
- ❌ 未検証（時間切れ、または取得エラー。次回セッションで再調査）

---

## 日本の小説（§4.5.1）

### High Priority（毎日チェック）

#### 1. 好書好日（朝日新聞） ⚠️
- **URL**: https://book.asahi.com/
- **RSS**: **未提供**（`/feed`、`/rss/` ともに 404、HTML内 `<link rel="alternate">` なし）。サイト本体は 200 で稼働中
- **形式**: HTML スクレイピング（トップページの新着記事リストをパースする運用を想定）
- **mainstream**: true
- **対象**: 朝日新聞の文芸書評・著者インタビュー・新刊情報。現代日本文学から海外文学まで横断
- **位置付け**: **国内文芸書評の最重要ハブ**。news_profile.md §4.5.1 の好む作家（村上春樹・平野啓一郎・吉田修一・小川哲・伊坂幸太郎等）の新刊レビュー・インタビューを最も網羅的に拾える。RSSがないため取得コストはかかるが、文芸面のカバー範囲を考えれば High 確定

#### 2. 本の雑誌オンライン ✅
- **URL**: https://www.webdoku.jp/
- **RSS**: https://www.webdoku.jp/atom.xml（Atom、Movable Type 配信、124KB）
- **形式**: Atom 1.0
- **mainstream**: true
- **対象**: 本の雑誌社系の書評・新刊情報・書店員レコメンド。エンタメ・ミステリ・ホラー・歴史小説に強い
- **位置付け**: **エンタメ・ミステリ系の最強ソース**。news_profile.md §4.5.1 の好む作家のうち東野圭吾・伊坂幸太郎・奥田英朗・米澤穂信・北方謙三・宮城谷昌光等のエンタメ・歴史系をカバー。本の雑誌社の **目利き感覚**（美意識2）と神山さんの嗜好の親和性が高い

### Medium Priority（候補が薄い日に拾う）

#### 3. ダ・ヴィンチWeb（KADOKAWA） ⚠️
- **URL**: https://ddnavi.com/
- **RSS**: **未提供**（`/feed/` 404、HTML内に `feed`/`rss` リンクなし）。代替として `https://ddnavi.com/sitemap.xml`（200、application/xml）で記事URL列挙が可能
- **形式**: sitemap.xml スクレイピング
- **mainstream**: false
- **対象**: 月刊ブックマガジン「ダ・ヴィンチ」のWeb版。新刊紹介、特集、著者インタビュー、ホラー・ミステリ・SF寄りも扱う
- **位置付け**: 好書好日が「新聞系の重厚」、本の雑誌が「老舗書評誌の硬派」だとすれば、ダ・ヴィンチは「**カルチャー誌寄りの軽快な書評**」。澤村伊智・三津田信三等のホラー・怪奇系（§4.5.1）の特集が定期的に組まれる。サイトマップ経由のため取得コストやや高く Medium

---

## 海外純文学（§4.5.2）

### High Priority（毎日チェック）

#### 4. New York Review of Books（NYRB） ✅
- **URL**: https://www.nybooks.com/
- **RSS**: https://www.nybooks.com/feed/
- **language**: en
- **形式**: RSS 2.0（nginx 配信）
- **mainstream**: true
- **対象**: 海外文学・哲学・歴史・社会論考の長文書評（英語原文）
- **位置付け**: **海外純文学批評の本丸**。news_profile.md §4.5.2 の好む作家（マルケス・クンデラ・イシグロ・ウエルベック・チュツオーラ）の **作品論・著者論** を最も深く扱う英語誌。マルケスのマジックリアリズム論、ウエルベック新作論などが定期的に出る。**英語原文のまま採用**（§5 編集ポリシー）

#### 5. The Paris Review ✅
- **URL**: https://www.theparisreview.org/
- **RSS**: https://www.theparisreview.org/blog/feed/（ブログ枠、Cloudflare 配信）。本誌（季刊）の `/feed/` 単独は 403
- **language**: en
- **形式**: RSS 2.0
- **mainstream**: false
- **対象**: 短編小説、詩、著者インタビュー（"Art of Fiction" シリーズが看板）
- **位置付け**: **作家インタビューの最高峰**。"Art of Fiction" シリーズはマルケス・クンデラ・イシグロを含む現代文学の主要作家へのロングインタビューを蓄積。**周縁・境界・他者の視点から書く作家**（news_profile.md §4.5.2 の共通項）の発掘に最適

### Medium Priority（候補が薄い日に拾う）

#### 6. Words Without Borders ✅
- **URL**: https://wordswithoutborders.org/（apex ドメイン、`www.` 付きは 301 リダイレクト）
- **RSS**: https://wordswithoutborders.org/feed/
- **language**: en
- **形式**: RSS 2.0
- **mainstream**: false
- **対象**: 世界各国の翻訳文学（英語以外の文学を英訳して紹介）。アフリカ・南米・東欧・中東・東南アジア
- **位置付け**: news_profile.md §4.5.2 の **エイモス・チュツオーラ（西アフリカ・ヨルバ口承文学）** に最も近接するソース。**「西洋メインストリーム文学の中心ではなく、周縁・境界・他者の視点から書く作家」**（§4.5.2 共通項）を発掘する役割。マルケスの後継者にあたる南米作家、ヨルバ・スワヒリ等のアフリカ口承文学の英訳もここで知れる

---

## SF（§4.5.3）

### High Priority（毎日チェック）

#### 7. Reactor（旧 Tor.com） ✅
- **URL**: https://reactormag.com/
- **RSS**: https://reactormag.com/feed/（**ブラウザUAが必要**、デフォルトUAでは 403）
- **language**: en
- **形式**: RSS 2.0
- **mainstream**: true
- **対象**: 米SF出版社 Tor の公式オンライン誌（2024年に Tor.com から Reactor に改称）。SF短編、書評、コラム、新刊情報
- **位置付け**: **米SF業界の現在地**を最も濃く伝える。news_profile.md §4.5.3 の **未読領域「ニューウェーブ・サイバーパンク・新しい波（ジェミシン、ベッキー・チェンバーズ等）」の入り口提案** に最適。テッド・チャンも複数寄稿経験あり。フェッチ層には **User-Agent 設定**（companies.md の HBR.org とは別パターンの脆さ）を必ず仕込むこと

### Medium Priority（候補が薄い日に拾う）

#### 8. SFマガジン（早川書房） ⚠️
- **URL**: https://www.hayakawa-online.co.jp/sfmagazine/
- **RSS**: **未提供**（`/feed/`、`/sfmagazine/feed/` ともに 302/404、早川書房は **SNS（X/Bluesky/Instagram）配信中心**）。サイト本体は 200
- **形式**: HTML スクレイピング（新刊号・特集記事ページから新着抽出）
- **mainstream**: true
- **対象**: 国内SF発信源。月刊「SFマガジン」掲載作・特集の Web 告知、早川書房 SF 単行本・文庫の新刊情報
- **位置付け**: **国内SF読者にとっての中央広場**。news_profile.md §4.5.3 の **既読作家の新刊・新訳を確実に拾う** 役割（テッド・チャン新訳・小川哲新刊・劉慈欣続編 等）。RSS不在のため Reactor/Locus とは別系統で運用、フェーズ2で X アカウント（@Hayakawashobo）の取り込みも検討

#### 9. Locus Magazine ✅
- **URL**: https://locusmag.com/
- **RSS**: https://locusmag.com/feed/（Sucuri WAF 経由配信）
- **language**: en
- **形式**: RSS 2.0
- **mainstream**: false
- **対象**: SF/Fantasy 業界誌（米）。新刊レビュー、Hugo/Nebula/Locus 賞関連、作家訃報・受賞歴
- **位置付け**: **SF業界の動きを俯瞰** する用途。Reactor が「Tor 視点」だとすれば Locus は「業界横断」。受賞情報は news_profile.md §4.5.3 の **思弁的・哲学的SFの新作・隠れた良作の発掘** にも有用。新刊情報主体で論考は少なめ、Medium で十分

---

## 自然科学ノンフィクション（§4.5.4）

### High Priority（毎日チェック）

#### 10. Quanta Magazine ✅
- **URL**: https://www.quantamagazine.org/
- **RSS**: https://www.quantamagazine.org/feed/（Cloudflare 配信）
- **language**: en
- **形式**: RSS 2.0
- **mainstream**: true
- **対象**: 数学・物理・生命科学・コンピュータサイエンスの最新研究を一般向け長文記事で解説（Simons 財団運営）
- **位置付け**: **英語圏で最も評価の高い科学誌**。news_profile.md §4.5.4 の嗜好の本質「**『物事の中身』より『物事の枠組み』、『個別の事象』より『認知や知の構造』を好む**」と最も合致する。学問領域を架橋する記事（数学×物理、生命科学×情報理論等）が看板。**ロヴェッリ的な書き手** を最も発掘しやすい場

### Medium Priority（候補が薄い日に拾う）

#### 11. Nautilus ✅
- **URL**: https://nautil.us/
- **RSS**: https://nautil.us/feed（10KB、`/feed/` は 308 → `/feed`）
- **language**: en
- **形式**: RSS 2.0
- **mainstream**: false
- **対象**: テーマ別科学エッセイ誌。脳科学・認知科学・物理・生物・哲学を文学的な筆致で
- **位置付け**: news_profile.md §4.5.4 の好む著者 **オリヴァー・サックス・ダマシオ・ラマチャンドラン（脳科学）、ロヴェッリ（物理）** の系譜の現代版。Nautilus 編集部は **「学問領域を架橋する書き手」**（§4.5.4 嗜好の本質）を意識的に集めている。Quanta より文学寄り、相補的に運用

#### 12. 日経サイエンス ✅
- **URL**: https://www.nikkei-science.com/
- **RSS**: https://www.nikkei-science.com/?feed=rss2（WordPress 標準、2026-04-24 lastBuildDate）
- **形式**: RSS 2.0
- **mainstream**: true
- **対象**: Scientific American 日本語版＋日本独自記事。物理・宇宙・脳科学・生命科学・数学の月刊誌
- **位置付け**: **日本語の自然科学ノンフィクション** の中核。Quanta/Nautilus が英語論考のため、**日本語で読める深掘り記事** をここで補強。月刊のため新着頻度は低いが、特集号テーマで neighborhood は明示される

### Reference（月1の俯瞰用）

#### 13. The Marginalian（旧 Brain Pickings） ✅
- **URL**: https://www.themarginalian.org/
- **RSS**: https://www.themarginalian.org/feed/（Cloudflare 配信）
- **language**: en
- **形式**: RSS 2.0
- **mainstream**: false
- **対象**: マリア・ポポバ運営の文学・科学・哲学エッセイ誌（**科学・哲学・文学の交差**）
- **位置付け**: news_profile.md §4.5.4 の **未踏だが関心高（朝刊が入り口提案を担う）「科学哲学：ポパー・クーン・ファイヤーアーベント等」** への入り口として最適。15年以上書き続けられる老舗、文学と科学を往復する書評は **美意識3「学問領域を架橋する」** の体現。週1〜2本の更新ペースで Reference 扱いが妥当

---

## 一次情報URL（参考メモ）

調査過程で収集した、RSS/メタデータ整備の手がかりとなる一次情報URL：

- **NYRB Daily Blog**: https://www.nybooks.com/daily/ （メイン誌より速報性、別RSSあり要調査）
- **The Paris Review Interviews**: https://www.theparisreview.org/interviews/ （"Art of Fiction" シリーズ、別RSS要調査）
- **Reactor / Tor.com 改称履歴**: 2024年 Tor.com → Reactor に改称、`tor.com/feed/` も 403 で同じ事情
- **早川書房 X アカウント**: @Hayakawashobo（フェーズ2で X RSS化を検討）
- **Words Without Borders Daily**: https://wordswithoutborders.org/dispatches/ （ブログ枠、メイン誌と別配信の可能性）
- **Locus Online Reviews**: https://locusmag.com/category/reviews/ （カテゴリ別RSS要調査）

---

## 次回セッションのTODO

優先度順：

1. **好書好日 のスクレイパ設計** — RSS不在のため `book.asahi.com/` のトップページから新着記事リストを抽出するパーサが必要。文芸書評の中核なので優先度最高
2. **早川書房 X アカウントの RSS 化** — `@Hayakawashobo` を nitter / RSSHub 経由で RSS 化する設計（フェーズ2）。SFマガジンの代替アクセスとして
3. **Reactor の User-Agent 設定の永続化** — フェッチ層に **デフォルトで browser UA** を設定するか、サイト別UA上書きの設計。companies.md の HBR.org（HTTPS問題）と並ぶ「サイト別フェッチ調整」の事例
4. **NYRB Daily Blog / The Paris Review Interviews の別RSS探索** — メイン誌RSSと別に、より深い枠の取得可能性
5. **Words Without Borders の `www.` 問題ハンドリング** — apex 推奨のため `wordswithoutborders.org/feed/` で固定、`www.` 付きは 301 のリダイレクト処理が要る（companies.md の `gaisyoku.biz`/`gaishoku` の教訓と同型）
6. **重複排除ロジック**（NYRB ↔ The Paris Review の同じ作家インタビュー、Quanta ↔ Nautilus の同じ研究紹介）
7. **「未読・読みたい」枠の意識的提案ロジック** — news_profile.md §4.5.3 の SF未読領域（ニューウェーブ・サイバーパンク・新しい波）、§4.5.4 の科学哲学について、Reactor/Marginalian で該当キーワードヒット時に **「読者がまだ手をつけていない領域」マーカー** を付ける選定ロジック（フェーズ2、§5.4「読みたいが読めていない領域への入り口提案」を反映）

---

**文書バージョン**：v0.1
**作成日**：2026/4/27（火曜夜セッション）
**更新履歴**：
- v0.1（2026/4/27）：初版作成、13ソース整備（✅9件、⚠️3件、❌0件）。ALL REVIEWS は事前合意で除外。SFマガジンは早川書房がSNS中心配信のため RSS 不在、HTMLスクレイピング運用。Reactor は browser UA 必須、フェッチ層への永続化が次回TODO。Words Without Borders は apex ドメイン推奨

**次回見直し**：`sources/{music,outdoor,cooking,academic}.md` 着手時、または `fetch.py` 設計時
