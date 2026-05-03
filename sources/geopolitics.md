# Geopolitics — 国際情勢・地政学の情報源

このファイルは Kamiyama Tribune の **国際情勢・地政学** 軸の情報源リストである。
第1面（The Front Page）の国際面トップ枠、第3面（General News）の国際情勢枠、第4面（Arts & Letters）の論考枠に流れるソースを、**ウォッチ優先順位（高 / 中 / 低）×ソース** のマトリクスで記録する。

グローバル経済・経営論考は `sources/business.md` を参照。3社事業文脈は `sources/companies.md` を参照。

選定の方針は `news_profile.md` §4.3 を参照。**「日本に影響を与える動き」を察知する視点**で読むこと、**読み方の好みは「分析・論考 → 構造的・長期視点 → 速報 → 複数視点比較」の順**で、**速報より深さ、現在より構造**を重視する。好む論者は **鈴木一人**（経済安全保障）・**ジョセフ・ナイ**（ソフトパワー）・**小泉悠**（ロシア軍事）であり、**軍事・経済・テクノロジーが交差する境界領域**を捉えるソースを優先採用すること。

**ステータス凡例**：
- ✅ 検証済み（フィード/URLが実際に取得できることを確認）
- ⚠️ 一部未検証（URLは到達するが、フィード形式・更新頻度・カテゴリ分けは要追加調査、または公式RSS不在で代替手段で運用）
- ❌ 未検証（時間切れ、または取得エラー。次回セッションで再調査）

---

## High Priority（毎日チェック）

### 1. Foresight（新潮社） ✅
- **URL**: https://www.fsight.jp/
- **RSS**: https://www.fsight.jp/list/feed/rss
- **形式**: RSS 2.0（検証時 2026-04-26 配信「『危険すぎるAI』の『持てる者と持たざる者』」を取得確認、カテゴリ「経済・ビジネス」「テック」付与）
- **mainstream**: true
- **対象**: 国際情勢、地政学、経済安全保障、技術覇権、エネルギー、米中関係（日本語の構造分析）
- **位置付け**: **日本語の国際情勢分析の最重要ソース**。news_profile.md §4.3 の論者である **鈴木一人** が頻繁に寄稿する場の一つ。**会員制（有料）** だが、RSSには無料公開記事＋有料記事のリード文が混在配信される。本紙では「日本人筆者による日本語論考」を優先する方針（§5 編集ポリシー）と最も親和性が高い

### 2. Foreign Affairs（CFR） ✅
- **URL**: https://www.foreignaffairs.com/
- **RSS**: https://www.foreignaffairs.com/rss.xml
- **language**: en
- **形式**: RSS（13KB、Cloudflare 配信）
- **mainstream**: true
- **対象**: 国際関係論、地政学、外交政策、軍事戦略、グローバル経済秩序（英語原文）
- **位置付け**: **英語圏の国際情勢論考の本丸**。Council on Foreign Relations（CFR）の機関誌で、ジョセフ・ナイ・ヘンリー・キッシンジャー級の論者が執筆。news_profile.md §4.3 の「**構造的・長期視点（10-20年スパン）**」「**分析・論考軸**」に最も合致。**英語原文のまま採用**（§5 編集ポリシー）

### 3. Project Syndicate ✅
- **URL**: https://www.project-syndicate.org/
- **RSS**: https://www.project-syndicate.org/rss
- **language**: en
- **形式**: RSS（32KB、cache無効ヘッダで常に最新）
- **mainstream**: false
- **対象**: 国際関係、経済、政治、社会のオピニオンコラム配信（150カ国以上のメディアにシンジケーション）
- **位置付け**: **ジョセフ・ナイの定期コラム配信元**。news_profile.md §4.3 で名指しされている論者にダイレクトにアクセスできる唯一のソース。同じくジョセフ・スティグリッツ・ヌリエル・ルビーニ・ケネス・ロゴフ等の経済学者・国際関係学者のコラムが日次で配信される。**論者名でフィルタ運用**（フェーズ2の選定ロジック実装時）

### 4. Reuters World ⚠️
- **URL**: https://www.reuters.com/world/
- **RSS**: **公式RSS廃止**（business.md と同じ事情）。代替として **Google News RSS プロキシ** `https://news.google.com/rss/search?q=site:reuters.com+world&hl=en-US&gl=US&ceid=US:en` で間接取得可（200確認）
- **language**: en
- **形式**: RSS 2.0（Google News 経由）
- **mainstream**: false
- **対象**: グローバル速報（紛争・選挙・外交・首脳会談）
- **位置付け**: news_profile.md §4.3 の「**速報は軽く押さえる程度**」方針に従い、**事実関係の裏取り** として運用。論考軸（Foreign Affairs、Project Syndicate）の記事内容を Reuters の事実報道で確認する用途。プロキシ運用リスクは business.md と共通

---

## Medium Priority（候補が薄い日に拾う）

### 5. Foreign Policy ✅
- **URL**: https://foreignpolicy.com/
- **RSS**: https://foreignpolicy.com/feed/
- **language**: en
- **形式**: RSS 2.0（Cloudflare 配信、CORS 全開放）
- **mainstream**: false
- **対象**: 外交政策、地政学、グローバル経済、テクノロジー外交（Foreign Affairs より速報＋論考の中間層）
- **位置付け**: **Foreign Affairs と相補的**。Foreign Affairs が「学術寄りの長文論考」なら Foreign Policy は「実務家向けの中尺解説」。news_profile.md §4.3 の **「複数視点比較」**（読み方好みの4位）の素材として、同じ事象に対する Foreign Affairs と Foreign Policy の論調差を見せる運用が可能

### 6. Brookings Institution ✅
- **URL**: https://www.brookings.edu/
- **RSS**: 複数エンドポイント稼働
  - 研究全般: https://www.brookings.edu/research/feed
  - トピック別（外交政策）: https://www.brookings.edu/topic/foreign-policy/feed
  - ブログ「Order from Chaos」: https://www.brookings.edu/blog/order-from-chaos/feed
- **language**: en
- **形式**: RSS 2.0
- **mainstream**: false
- **対象**: 米シンクタンク Brookings の研究レポート・コラム（外交、経済、ガバナンス、技術政策）
- **位置付け**: **シンクタンク3点セット**（Brookings／CSIS／RAND）の中で **政策提言の具体性が最も高い**。トピック別RSSが提供されているため、外交政策に絞った購読が可能。フェーズ2では `/topic/asia/feed` `/topic/economics/feed` 等への拡張を検討

### 7. CSIS（戦略国際問題研究所） ✅
- **URL**: https://www.csis.org/
- **RSS**: https://www.csis.org/rss.xml（`/analysis/feed` は 404、サイトルートのみ稼働）
- **language**: en
- **形式**: RSS 2.0
- **mainstream**: false
- **対象**: 安全保障、防衛、サイバー、宇宙、技術と安全保障の交差領域
- **位置付け**: **軍事・経済・テクノロジーの交差領域**（news_profile.md §4.3 の「好む論者の共通項」）に最も近い米シンクタンク。中国・台湾・北朝鮮・ロシア関連レポートの質が高い。**全体RSSのみで分野別がないため、タイトル/著者でフィルタ必要**

### 8. War on the Rocks ✅
- **URL**: https://warontherocks.com/
- **RSS**: https://warontherocks.com/feed/
- **language**: en
- **形式**: RSS（Cloudflare、text/xml）
- **mainstream**: false
- **対象**: 軍事・国家安全保障・外交の長文論考（現役・退役軍人、研究者、ジャーナリストが執筆）
- **位置付け**: news_profile.md §4.3 の **小泉悠**（ロシア軍事、現代の戦争論）の英語圏での近接ソース。**「軍事・経済・テクノロジーが交差する境界領域」** の具体例として最適。学術紀要より読みやすく、防衛白書より深い論考が日次で出る。優先度を Medium → High に引き上げる選択肢もあり、運用してから判断

---

## Reference（月1の俯瞰用）

### 9. RAND Corporation ✅
- **URL**: https://www.rand.org/
- **RSS**: https://www.rand.org/pubs/commentary.xml（旧 `/blog.xml`、`/news/rss.xml` は 301、現行は `/pubs/commentary.xml` で配信、17.8KB）
- **language**: en
- **形式**: RSS（CloudFront 配信）
- **mainstream**: false
- **対象**: 国家安全保障、テクノロジーと社会、健康、教育、労働政策の研究レポート＋コメンタリー
- **位置付け**: **政策研究の老舗**（1948年設立、米空軍系起源）。月数本ペースだが、**長期構造分析**（news_profile.md §4.3 の「10-20年スパン」）の代表格。中国軍事力評価、AI と国家安全保障、宇宙ガバナンス等のテーマで定期的に重要レポートを出す

### 10. NBR（National Bureau of Asian Research） ❌
- **URL**: https://www.nbr.org/
- **RSS**: **未検証完了**（`/feed/`、`/publication-feed/` ともに 403、複数UAでも遮断、WebFetch も 403）。Imperva 系のbot対策で完全に閉じている可能性大
- **language**: en
- **形式**: ❌ プログラマティック取得不可
- **mainstream**: false
- **対象**: アジア太平洋地域の戦略・経済・安全保障研究（米中、インド太平洋、東南アジア）
- **位置付け**: **アジア軸の専門シンクタンク** として価値は高いが、配信インフラが閉じている。フェーズ1では断念。代替として CSIS のアジア関連研究、Brookings の `/topic/asia/feed`（フェーズ2拡張時）でアジア軸をカバーする方針。重要レポートは Twitter/LinkedIn 経由で察知して手動 URL 取得

### 11. 東京大学 公共政策大学院（GraSPP） ✅
- **URL**: https://www.pp.u-tokyo.ac.jp/
- **RSS**: https://www.pp.u-tokyo.ac.jp/feed/
- **形式**: RSS 2.0（WordPress 標準、検証時に最新10件取得確認、TECUSE/INPEX 寄付講座「エネルギー危機と現実的な脱炭素の道筋」、SSU Forum「中東欧の民主化の波」等の本物）
- **mainstream**: false
- **対象**: 公共政策、国際関係、経済安全保障、エネルギー政策、防災・危機管理（シンポジウム・研究セミナー告知が中心）
- **位置付け**: **鈴木一人 教授の在籍機関**。news_profile.md §4.3 で名指しされている論者の **講演・シンポジウム情報をリアルタイムに察知** できる。記事配信ではなくイベント告知のため Reference 扱い。本紙では「今週の講演・シンポジウム」枠（フェーズ2で導入検討）に流す想定

---

## 一次情報URL（参考メモ）

調査過程で収集した、RSS/メタデータ整備の手がかりとなる一次情報URL：

- **Foresight 編集部**: https://www.fsight.jp/list/category/editor （編集部執筆記事一覧）
- **Project Syndicate Authors（ジョセフ・ナイ）**: https://www.project-syndicate.org/columnist/joseph-s-nye （著者別ページ、フェーズ2の論者フィルタで使用）
- **Brookings 全RSS一覧**: https://www.brookings.edu/feeds/ （存在不明、`/feeds/all.xml` は404確認）→ topic別RSSパターン `/topic/{slug}/feed` を運用
- **CSIS Programs**: https://www.csis.org/programs （プログラム単位のページ、各プログラムの個別RSSは未提供確認）
- **RAND Commentary（旧）**: https://www.rand.org/blog.xml → 301 で `/pubs/commentary.xml` にリダイレクト（旧URLでブクマしているソフトは要更新）
- **GraSPP イベントカレンダー**: https://www.pp.u-tokyo.ac.jp/event/ （シンポジウム・研究セミナー一覧）

---

## 次回セッションのTODO

優先度順：

1. **小泉悠 の専属ソース整備** — news_profile.md §4.3 で名指しされているが、**東大先端研**（GraSPP とは別組織）所属で本ファイルにソース未整備。`https://www.rcast.u-tokyo.ac.jp/` のフィード調査と、War on the Rocks の小泉悠寄稿パターンの確認をフェーズ1で実施
2. **NBR の代替ルート検討** — フェーズ1では断念したが、アジア軸の補強が必要であれば **Carnegie Endowment for International Peace**（`carnegieendowment.org`）または **Lowy Institute**（豪州、AsPac 特化）の RSS 検証
3. **Brookings トピック別RSS の拡張** — 現状は `/topic/foreign-policy/feed` のみ採用。`/topic/asia/feed`、`/topic/economics/feed`、`/topic/technology-innovation/feed` 等の追加検証
4. **Project Syndicate の論者フィルタ実装** — RSS 全件は1日数十本配信される。**ナイ・スティグリッツ・ロゴフ・ルビーニ等の優先論者リスト**を `news_profile.md` §4.3 に明示して、フェーズ2でフィルタ実装
5. **Foreign Affairs の特集号判定** — Foreign Affairs は隔月刊で **特集号テーマ** が変わる。RSS から特集号テーマを抽出して、その月は High に引き上げる運用ルール
6. **重複排除ロジック**（特に Foreign Affairs ↔ Foreign Policy ↔ Project Syndicate の論者重複、CSIS ↔ Brookings のレポート重複）
7. **Foresight の有料記事ハンドリング** — 会員制サイトのため、本紙では「**有料記事はリード文＋Foresight への購読促進リンク**」の形式で扱う必要あり。ノイズ判定にならないよう運用ルールを fetch ロジックに組み込む

---

**文書バージョン**：v0.1
**作成日**：2026/4/27（火曜夜セッション）
**更新履歴**：
- v0.1（2026/4/27）：初版作成、11ソース整備（✅9件、⚠️1件、❌1件）。Brookings はトピック別RSS が稼働しているため `/topic/foreign-policy/feed` を採用。NBR は Imperva 完全遮断のためフェーズ1断念。Reuters World は business.md と同様 Google News プロキシで代替

**次回見直し**：`sources/{books,music,outdoor,cooking,academic}.md` 着手時、または `fetch.py` 設計時
