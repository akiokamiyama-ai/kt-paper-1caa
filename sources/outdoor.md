# Outdoor — アウトドア（UL系・とがったプロダクト）の情報源

このファイルは Kamiyama Tribune **第5面 Leisure アウトドア枠** の情報源リストである。
神山さんの嗜好の本質「**個人がやっているような小さなブランド**」「**UL思想**」「**とがった本質的なプロダクト**」を踏まえ、**ウォッチ優先順位（高 / 中 / 低）×ソース** のマトリクスで記録する。

選定の方針は `news_profile.md` §4.7 を参照。Tribune全体の選定基準は同文書 §3 の美意識7項目と §5 の横断ルール。特に「**目利き感覚で主流外の本質を発掘する**」（美意識2）と「**ハードコア登山者向け技術論は弾く**」（§4.7 設計含意）を強く意識すること。

**ステータス凡例**：
- ✅ 検証済み（フィード/URLが実際に取得できることを確認）
- ⚠️ 一部未検証（URLは到達するが、フィード形式・更新頻度・カテゴリ分けは要追加調査、または公式RSS不在で代替手段で運用）
- ❌ 未検証（時間切れ、または取得エラー。次回セッションで再調査）

**領域全体の特徴**：日本語のアウトドアメディアは **RSS配信を広く廃止** している（10件中6件が ⚠️）。Shopify ストアフロント化（山と道、ハイカーズデポ）や SaaS 化（YAMAP）の影響。**HTMLスクレイピング前提の領域** として `fetch.py` 設計時に専用パーサ群が必要。

---

## 国内UL系・ガレージブランド（毎日チェック）

### 1. 山と道 Journals ⚠️
- **URL**: https://www.yamatomichi.com/journals
- **RSS**: **未提供**（`/journals/feed`、`/feed/` ともに 308 → 404、Shopify ベースのストアフロント上に WordPress 風記事が乗る構成。HTML内に RSS リンクなし）
- **形式**: HTML スクレイピング（`/journals` インデックスページから新着記事抽出）
- **mainstream**: false
- **対象**: 日本UL系の最重要ブランド「山と道」自社メディア。製品開発思想、ハイカーインタビュー、フィールドレポート、UL縦走記
- **位置付け**: **国内UL思想の中核ソース**。news_profile.md §4.7 既知ブランド筆頭、嗜好の本質「**UL思想・職人プロダクト**」を最も体現。Journals の長文記事は **読み物としての価値も高い**（製品紹介に留まらない哲学的記事）。RSS不在は痛いが High 確定

### 2. ハイカーズデポ ⚠️
- **URL**: https://hikersdepot.jp/
- **RSS**: **未提供**（`/feed/`、`/blog/feed`、`/news/feed` すべて 404、Shopify ベース、HTML内 RSS リンクなし）
- **形式**: HTML スクレイピング
- **mainstream**: true
- **対象**: 国内UL系セレクトショップの目利き発信。海外UL系ブランド（Hyperlite Mountain Gear、Zpacks、Pa'lante 等）の **国内取り扱い情報**、新作レビュー、ハイク記事
- **位置付け**: **海外UL系ブランドの日本語入り口**。news_profile.md §4.7 設計含意「**海外UL系ブランドの紹介・解説（Hyperlite、Zpacks、Pa'lante 等）**」の起点。Pa'lante Packs V3 が本紙第5面ダミーで紹介された経緯（archive/2026-04-25.html）も、ハイカーズデポを情報源として想定したもの

### 3. Hike Life（山と道メディア） ⚠️
- **URL**: https://www.yamatomichi.com/hikelife
- **RSS**: **未提供**（同 yamatomichi.com 配下、ストアフロント上のメディア枠）
- **形式**: HTML スクレイピング
- **mainstream**: false
- **対象**: 山と道が運営する **ハイカーカルチャー誌**。ロングディスタンスハイク、UL思想の哲学的展開、海外ハイカー紹介
- **位置付け**: 山と道 Journals が「**製品起点**」とすれば Hike Life は「**カルチャー起点**」。神山さんの **「ソロキャンプ・縦走への興味」** に対する読み物的な入り口。山と道 Journals と同じドメインのため、フェッチ層では `/journals` と `/hikelife` を **同一スクレイパ** で扱うのが合理的

---

## 国内ハイク実用情報（Medium）

### 4. YAMAP マガジン ⚠️
- **URL**: https://yamap.com/magazine
- **RSS**: **未提供**（`/feed` 500 サーバエラー、`/magazine/feed` 404、HTML内 RSS リンクなし、SNSのみ：YouTube/X/Instagram/Facebook/note）
- **形式**: HTML スクレイピング
- **mainstream**: true
- **対象**: YAMAP（登山GPS/SNSアプリ）運営のハイクメディア。ルート紹介、季節情報、ギアレビュー、初心者向けハウツー
- **位置付け**: news_profile.md §4.7 設計含意「**高尾山周辺・東京近郊の実用情報（季節情報、隣接ルート等）**」の中核。ヤマケイオンラインが「山岳雑誌系」、YAMAP マガジンが「**SNS時代のライト層向け**」。実用情報が中心で哲学的論考は薄いため Medium

### 5. ヤマケイオンライン ⚠️
- **URL**: https://www.yamakei-online.com/
- **RSS**: **未提供**（`/feed`、`/news/feed` ともに 404、HTML内 RSS リンクなし）
- **形式**: HTML スクレイピング
- **mainstream**: false
- **対象**: 山と渓谷社（**山岳雑誌の老舗**）のオンライン版。月刊『山と溪谷』『岳人』『ワンダーフォーゲル』の Web 連携記事、登山ニュース、ギア・登山道情報
- **位置付け**: news_profile.md §4.7 **「いつかやりたい」領域への入り口** の中で **縦走・最初の一歩** に最も貢献するソース。ただし山と道/ハイカーズデポ系の UL 思想とは別系統（伝統的山岳文化寄り）のため Medium。**「ハードコア登山者向け技術論」（§4.7 弾くもの）の判定** がフィルタに必要

---

## 海外UL系（Reference〜Medium）

### 6. Backpacking Light ✅
- **URL**: https://backpackinglight.com/
- **RSS**: https://backpackinglight.com/feed/（Cloudflare 配信）
- **形式**: RSS 2.0
- **mainstream**: true
- **対象**: **米UL業界の総本山**。ギアレビュー、ロングトレイル記、UL哲学の論考、有料フォーラム
- **位置付け**: news_profile.md §4.7 嗜好の本質「**UL思想**」「**とがった本質的なプロダクト**」の英語圏での最重要ソース。Hyperlite/Zpacks/Pa'lante 等の **メーカー直接取材記事** が定期的に出る。**英語原文のまま採用**（§5 編集ポリシー）

### 7. The Trek ✅
- **URL**: https://thetrek.co/
- **RSS**: https://thetrek.co/feed/（Cloudflare 配信）
- **形式**: RSS 2.0
- **mainstream**: false
- **対象**: 米長距離縦走（Appalachian Trail / Pacific Crest Trail / Continental Divide Trail）の専門メディア。**ハイカー本人による日記形式の記事** が中心
- **位置付け**: news_profile.md §4.7 「**未踏で興味のある領域：縦走**」への **入り口の入り口**。「最初の縦走をどう準備するか」「装備リスト」「水場情報」等の **入門記事も豊富**。専門用語は多いがハードコア技術論ではなく、**個人の物語として読める** 点が神山さんの嗜好に合う

### 8. Section Hiker ✅
- **URL**: https://sectionhiker.com/
- **RSS**: https://sectionhiker.com/feed/（Cloudflare 配信）
- **形式**: RSS 2.0
- **mainstream**: false
- **対象**: 米個人ハイカー Philip Werner 運営のブログ。**ガレージブランド製品の徹底レビュー**、ロングトレイル記、UL ノウハウ
- **位置付け**: news_profile.md §4.7 嗜好の本質「**個人がやっているような小さなブランド**」への **個人ブログ視点でのアクセス**。Backpacking Light が「業界誌」、Section Hiker が「**個人の目利き**」。長年の運営で記事数が膨大、**美意識2（目利き感覚で主流外の本質）** との親和性が極めて高い

### 9. CleverHiker ✅
- **URL**: https://www.cleverhiker.com/
- **RSS**: https://www.cleverhiker.com/feed/（**ブラウザUA必須**、デフォルトUAでは 403。books.md Reactor、music.md なし、と並ぶ「サイト別フェッチ調整」事例）
- **形式**: RSS 2.0
- **mainstream**: false
- **対象**: 米ギアレビューサイト。テント・バックパック・スリーピング系の比較レビュー、UL寄り
- **位置付け**: Backpacking Light が「**論考・哲学**」、Section Hiker が「**個人視点のレビュー**」、CleverHiker は「**比較レビューに特化**」した三本柱の最後の1つ。神山さんが新しいギアを検討する際の参考情報として。フェッチ層には **User-Agent 設定の永続化が必須**

---

## ソロキャンプ（Reference）

### 10. ハピキャン ⚠️
- **URL**: https://hapicamper.jp/
- **RSS**: **未提供**（`/feed`、`/rss`、`/atom`、`/feed.xml`、`/rss.xml`、`/?feed=rss2` すべて応答なし、HTML内 RSS リンクなし）。サイト本体は 200
- **形式**: HTML スクレイピング
- **mainstream**: false
- **対象**: 国内キャンプメディア（GMOペパボ系）。**ソロキャンプ入門**、キャンプ場レビュー、簡単キャンプ料理、初心者向けギア紹介
- **位置付け**: news_profile.md §4.7 「**未踏で興味のある領域：ソロキャンプ**」への入り口。**ハードコアソロキャン論ではなくライト層向け** で、「やりたいが未実行」段階の神山さんに最適な視座。Reference 扱いだが、実際にソロキャン開始時には Medium に昇格

---

## 一次情報URL（参考メモ）

調査過程で収集した、RSS/メタデータ整備の手がかりとなる一次情報URL：

- **山と道 商品ページ起点**: https://www.yamatomichi.com/products （新製品リリース察知用）
- **ハイカーズデポ Twitter/X**: ガレージブランド最新作の最速察知ルート（フェーズ2でRSS化検討）
- **YAMAP 全国の山活動データ**: https://yamap.com/maps （ルート情報の二次活用）
- **山と渓谷 編集部 X**: ヤマケイ Web 化されない情報の取得
- **Hyperlite Mountain Gear**: https://www.hyperlitemountaingear.com/blogs/news （海外UL個別ブランドの最初の検証対象、フェーズ2）
- **Pa'lante Packs**: https://palantepacks.com/blogs/news （同上、本紙ダミーで言及済）

---

## 次回セッションのTODO

優先度順：

1. **HTMLスクレイパ群の共通設計** — 10件中6件が ⚠️（スクレイピング運用）。**Outdoor領域専用のパーサ抽象化** が `fetch.py` リファクタリング時に最重要。山と道（Shopify）、YAMAP（SaaS）、ヤマケイ（独自CMS）でそれぞれ別パーサが必要
2. **CleverHiker の User-Agent 永続化** — フェッチ層の **サイト別フェッチ設定** に登録（books.md Reactor、companies.md HBR と並ぶ事例。3件目で **「サイト別UA上書き」を一級機能に格上げ** すべき判断材料が揃う）
3. **海外UL個別ブランドの直接購読**（フェーズ2） — Hyperlite Mountain Gear、Zpacks、Pa'lante Packs、MOONLIGHT GEAR、Locus Gear、Trail Bum の **公式ブログRSS** を個別検証。ハイカーズデポ経由の二次情報より一次情報が望ましい
4. **「ソロキャンプ・最初の縦走」入門記事マーカー設計** — news_profile.md §5.4「**読みたいが読めていない領域への入り口提案**」を反映。The Trek / Section Hiker / ハピキャン の記事から「初心者向け」「入門」キーワードでヒットした記事に **「入り口」マーカー** を付ける（フェーズ2）
5. **「ハードコア登山者向け技術論」フィルタ** — §4.7 弾くものとして明示されている。ヤマケイオンライン、Backpacking Light の一部記事に該当。**否定キーワード辞書**（「アルパインクライミング」「冬季縦走」「ロープ確保」等）で除外
6. **山と道 Journals × Hike Life の同一スクレイパ化** — 同ドメイン配下のため、`yamatomichi.com` 用パーサ1つで両方カバーできる設計
7. **アウトドア領域の重複排除** — 海外UL系記事は Backpacking Light / Section Hiker / CleverHiker で同じギアの異なるレビューが出るパターンが多い。**ギア名（製品型番）での重複検知** ロジック（フェーズ2）

---

**文書バージョン**：v0.1
**作成日**：2026/4/27（火曜夜セッション）
**更新履歴**：
- v0.1（2026/4/27）：初版作成、10ソース整備（✅4件、⚠️6件、❌0件）。**Outdoor領域は日本語メディアの RSS 廃止が顕著**、HTMLスクレイピング前提の領域として `fetch.py` 設計時に専用パーサ群が必要。CleverHiker は browser UA 必須、フェッチ層の永続化が次回TODO

**次回見直し**：`sources/{cooking,academic}.md` 着手時、または `fetch.py` 設計時
