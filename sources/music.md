# Music — 音楽（ロックフェス中心）の情報源

このファイルは Kamiyama Tribune **第5面 Leisure 音楽枠** の情報源リストである。
神山さんが**通っている3フェス**（フジロック・朝霧JAM・グリーンルーム）の最新情報を最優先で拾う設計。**ウォッチ優先順位（高 / 中 / 低）×ソース** のマトリクスで記録する。

選定の方針は `news_profile.md` §4.6 を参照。Tribune全体の選定基準は同文書 §3 の美意識7項目と §5 の横断ルール。特に「**音楽×ロケーション×文化の3点セット**」「**地方小規模フェスへの情報感度を高く**」「**目利き発掘で新しいアーティスト紹介**」を強く意識すること。

**ステータス凡例**：
- ✅ 検証済み（フィード/URLが実際に取得できることを確認）
- ⚠️ 一部未検証（URLは到達するが、フィード形式・更新頻度・カテゴリ分けは要追加調査、または公式RSS不在で代替手段で運用）
- ❌ 未検証（時間切れ、または取得エラー。次回セッションで再調査）

---

## フェス公式（毎日チェック）

### 1. SMASH（フジロック・朝霧JAM 共通主催元） ⚠️
- **URL**: https://smash-jpn.com/
- **RSS**: **未提供**（`/feed/` 404、HTML内に `feed`/`rss` リンクなし）。サイト本体は 200
- **形式**: HTML スクレイピング（トップページの NEWS セクションをパース）
- **mainstream**: false
- **対象**: フジロック・朝霧JAM 両方の公式情報。ラインナップ発表、チケット販売、タイムテーブル、設営/撤収告知
- **位置付け**: **通っている3フェスのうち2フェスを束ねる最重要ソース**。RSSがないのは痛いが、フェス前後の情報密度を考えれば High 確定。「次のフェスまで X日」のカレンダー要素（news_profile.md §4.6 設計含意）の **データ起点** にもなる

### 2. GREENROOM 公式 ✅
- **URL**: https://greenroom.jp/
- **RSS**: https://greenroom.jp/feed/
- **形式**: RSS 2.0
- **mainstream**: false
- **対象**: グリーンルームフェス（横浜赤レンガ）の公式情報。サーフカルチャー寄りのラインナップ、関連イベント
- **位置付け**: 通っている3フェスの最後の1つ。RSS稼働で取得コスト最低。**自然・場所・文化が結びついたフェス体験**（§4.6 哲学）を最も体現する横浜のロケーション軸

### 3. サマーソニック（クリエイティブマン） ✅
- **URL**: https://www.summersonic.com/
- **RSS**: https://www.summersonic.com/feed/
- **形式**: RSS 2.0
- **mainstream**: false
- **対象**: サマソニ公式情報。ラインナップ、チケット、ステージ構成
- **位置付け**: news_profile.md §4.6 の **興味があるが行っていないフェス** の筆頭。海外大物来日のプラットフォームとして、たとえ参加せずとも **「今年のラインナップ」** は知っておきたい。神山さんの好むアーティスト（Radiohead、Arcade Fire、Stone Roses 等のUK系）の出演察知に重要

### 4. ライジングサン（WESS） ⚠️
- **URL**: https://rsr.wess.co.jp/
- **RSS**: **未提供**（`/feed/`、`/news/feed/` ともに 404）。サイト本体は 302 リダイレクト
- **形式**: HTML スクレイピング
- **mainstream**: false
- **対象**: RISING SUN ROCK FESTIVAL（北海道石狩湾）の公式情報
- **位置付け**: §4.6 **興味があるが行っていないフェス** のもう一つ。北海道という **ロケーション軸** が他フェスと差別化（Greenroom が海、フジが山、ライジングが大地）。神山さんの「自然・場所・文化」哲学に合う構造のため、HTMLスクレイピングのコストを払ってでも追う価値あり

---

## フェス情報まとめ（Medium）

### 5. Festival Life ✅
- **URL**: https://festival-life.com/
- **RSS**: https://festival-life.com/feed
- **形式**: RSS 2.0
- **mainstream**: true
- **対象**: 国内フェス情報の網羅的まとめ。大型フェスから **地方小規模フェスまで** カバー
- **位置付け**: news_profile.md §4.6 の **「地方小規模フェスへの情報感度を高く」** という設計含意の中核。SMASH/GREENROOM/サマソニ/ライジングサンの **「外」** を拾う。RSS稼働のため取得コスト最低、Medium だが運用後に High 昇格の可能性あり

---

## 国内ロックメディア（毎日〜週数回）

### 6. ナタリー音楽 ✅
- **URL**: https://natalie.mu/music
- **RSS**: https://natalie.mu/music/feed/news（Atom 1.0、21KB、2026-04-27 10:50 更新）
- **形式**: Atom 1.0
- **mainstream**: false
- **対象**: 国内音楽ニュース最頻ハブ。新譜リリース、ライブ告知、フェス出演情報、アーティスト関連ニュース全般
- **位置付け**: **国内音楽ニュースの最頻更新ソース**。サカナクション・くるり・三浦大知（§4.6 好むアーティスト 日本枠）の動向を最も網羅的に拾える。フェス公式が出さない「アーティスト個別の出演辞退/追加」もここで察知

### 7. rockinon.com（ロッキング・オン） ✅
- **URL**: https://rockinon.com/
- **RSS**: https://rockinon.com/news.rss（**異色パス、`/feed`、`/news/feed` ともに 404**）
- **形式**: RSS 2.0
- **mainstream**: false
- **対象**: 邦洋ロック総合。新譜レビュー、ライブレポート、インタビュー
- **位置付け**: **フジロック主催と密接な関係**（ロッキング・オン社が JAPAN/FES 系イベント主催元、フジロックの編集方針とも近接）。神山さんの好む UK ロック中核（Radiohead、OASIS、Stone Roses）系の取り扱いが厚い。**`/news.rss` の異色パスはフェッチ層に明示登録必須**（companies.md HBR.org 末尾`.rss`なし、books.md Reactor のbrowser UAと並ぶ「サイト別フェッチ調整」事例）

### 8. CINRA ⚠️
- **URL**: https://www.cinra.net/
- **RSS**: **廃止**（`/feed`、`/rss`、`/news/feed` いずれも 302 → `/news` HTMLページにリダイレクト、RSS 配信を停止）
- **形式**: HTML スクレイピング
- **mainstream**: false
- **対象**: 音楽・アート・カルチャー。インディー・実験的アーティスト、フェス特集、海外フェス紹介
- **位置付け**: ナタリー/ロッキング・オンが「商業ロック・大物」軸なら、CINRA は「**カルチャー・インディー・周縁**」軸。news_profile.md §4.6 **「目利き発掘」枠の新しいアーティスト紹介** の主力。RSS廃止が痛いが HTMLスクレイピングで継続採用

---

## 海外ロックメディア（Reference）

### 9. NME ✅
- **URL**: https://www.nme.com/
- **RSS**: https://www.nme.com/feed
- **形式**: RSS 2.0
- **mainstream**: true
- **対象**: UK音楽メディアの代表格。新譜・ライブ・フェス・インタビュー（英語原文）
- **位置付け**: **神山さんの好む UK ロック中核**（Radiohead、Stone Roses、Kula Shaker、OASIS、Arcade Fire — §4.6）の **祖国メディア**。Glastonbury / Reading & Leeds 等の海外フェス（**興味があるが行っていない**）の現地レポートもここで読める

### 10. Pitchfork ✅
- **URL**: https://pitchfork.com/
- **RSS**: https://pitchfork.com/feed/feed-news/rss（旧 `/rss/news/` は 301 リダイレクト）
- **形式**: RSS（CloudFront 配信、21KB）
- **mainstream**: false
- **対象**: 米インディー音楽の権威メディア。新譜レビュー（10点満点採点が看板）、コーチェラ等の海外フェスレポート
- **位置付け**: NME が UK 中心なら Pitchfork は **米インディー中心**。Arcade Fire の評価軸はここが最重要。**コーチェラ**（§4.6 海外フェス興味）の現地カバレッジが厚い

### 11. The Quietus ❌
- **URL**: https://thequietus.com/
- **RSS**: **未検証完了**（`/feed/`、`/feed.rss` ともに 403、ブラウザUA・Feedly bot UA・Feedburner UA すべて遮断）。Imperva 系 WAF で完全に閉じている
- **形式**: ❌ プログラマティック取得不可
- **mainstream**: false
- **対象**: UK alternative/avant rock メディア。商業性より目利き重視のレビュー、実験音楽・アンビエント・ポストロックも扱う
- **位置付け**: **目利き枠の本命候補だったが配信インフラが完全閉鎖**。代替候補としてフェーズ2で **Stereogum**（米インディー）、**DIY Mag**（UK）、**The Wire**（UK 実験音楽）の検証を予定。重要記事は Twitter/X 経由で察知して手動URL取得運用

---

## 一次情報URL（参考メモ）

調査過程で収集した、RSS/メタデータ整備の手がかりとなる一次情報URL：

- **フジロック公式（SMASH 内）**: https://www.fujirockfestival.com/ （SMASH と別ドメイン、`/feed` 要追加検証）
- **朝霧JAM 公式（SMASH 内）**: https://www.asagirijam.jp/ （こちらも独立ドメイン、要追加検証）
- **ナタリー全カテゴリ Feed**: https://natalie.mu/news.atom （音楽以外も含む全体フィード）
- **rockinon.com フェス系**: rockinon.com にはフェス特集用の別ドメイン `rijfes.jp`（ROCK IN JAPAN）あり
- **Pitchfork カテゴリ別**: `/rss/reviews/best-new-music/` 等の特化フィードあり、要追加検証

---

## 次回セッションのTODO

優先度順：

1. **フジロック・朝霧JAM 独立ドメインの RSS 検証** — `fujirockfestival.com`、`asagirijam.jp` には別の RSS が存在する可能性。SMASH の HTML スクレイピングを補完または代替できれば High 化
2. **The Quietus 代替の検討** — Stereogum、DIY Mag、The Wire の RSS 検証。目利き枠は本紙の差別化要素
3. **rockinon.com `/news.rss` 異色パスの永続化** — フェッチ層の **サイト別フェッチ設定** に rockinon.com を登録（companies.md HBR、books.md Reactor と同じ仕組み）
4. **CINRA の HTMLスクレイパ設計** — RSS廃止だが目利き枠の主力。トップ `/news` ページの構造解析と新着抽出ロジック
5. **「次のフェスまで X日」カウントダウンの データ源** — SMASH/GREENROOM/サマソニ/ライジングサンの開催日を `events.yaml` 的に外出し、紙面マストヘッドのカウントダウンに供給する設計（フェーズ2、design_spec.md のマストヘッド要素と接続）
6. **Pitchfork "Best New Music" カテゴリRSS** — 全件RSS はノイズ多め、`/rss/reviews/best-new-music/` 等の特化フィード検証で「目利き枠」を強化
7. **アーティスト個別フォロー** — Radiohead/Arcade Fire/サカナクション 等の **公式アカウント** を nitter / RSSHub 経由でRSS化（フェーズ3、X/Twitter からの個別取得）

---

**文書バージョン**：v0.1
**作成日**：2026/4/27（火曜夜セッション）
**更新履歴**：
- v0.1（2026/4/27）：初版作成、11ソース整備（✅7件、⚠️3件、❌1件）。SMASH/ライジングサン/CINRA は RSS不在のため HTMLスクレイピング、The Quietus は Imperva 完全遮断のためフェーズ1断念。rockinon.com は異色パス `/news.rss`、フェッチ層の永続化が次回TODO

**次回見直し**：`sources/{outdoor,cooking,academic}.md` 着手時、または `fetch.py` 設計時
