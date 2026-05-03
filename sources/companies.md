# Companies — 3社事業文脈の情報源

このファイルは Kamiyama Tribune「社長の朝会」面（紙面第2面）の情報源リストである。
3社それぞれについて、**ウォッチ優先順位（高 / 中 / 低）×ソース**のマトリクスでメタデータを記録する。

選定の方針は `news_profile.md` §4.2 を参照。Tribune全体の選定基準は同文書 §3 の美意識7項目と §5 の横断ルール。

**ステータス凡例**：
- ✅ 検証済み（フィード/URLが実際に取得できることを確認）
- ⚠️ 一部未検証（URLは到達するが、フィード形式・更新頻度・カテゴリ分けは要追加調査）
- ❌ 未検証（時間切れ、または取得エラー。次回セッションで再調査）

---

## Cocolomi（生成AI導入支援）

### High Priority（毎日チェック）

#### 1. 経済産業省ニュースリリース ✅
- **URL**: https://www.meti.go.jp/index.html
- **RSS**: https://www.meti.go.jp/ml_index_release_atom.xml
- **形式**: Atom
- **mainstream**: false
- **対象**: AI関連政策、補助金、ガイドライン、産業政策全般
- **位置付け**: 補助金・ガイドラインは事業の追い風を予測する最重要情報。AI事業者ガイドライン、AI戦略会議、DX関連支援策などを早期に捉える

#### 2. PR TIMES 生成AIタグ ⚠️
- **URL**: https://prtimes.jp/topics/keywords/生成AI
- **RSS**: 未提供（タグ単位のフィード配信なし。会社単位のRSSのみ提供 `companyrdf.php?company_id=...`）
- **形式**: Web Fetch（HTML一覧をスクレイピング）
- **mainstream**: false
- **対象**: 日本企業の生成AI関連プレスリリース（導入事例、サービス開始、調達、提携等）
- **位置付け**: 「日本企業の生成AI導入事例」を最も網羅的に拾える。ただしノイズ多め（広告色濃いリリース・無関係なゲームAIリリース等）。タイトル・配信元企業でフィルタが必要

#### 3. AINOW ⚠️
- **URL**: https://ainow.ai/
- **RSS**: 未提供（HTML上に明示なし。WordPress標準の `/feed/` 試行は要再検証）
- **形式**: Web Fetch / Web Scraping
- **mainstream**: false
- **対象**: 生成AI、ChatGPT、LLM、機械学習、DX、Web3 等のAI専門メディア（株式会社ディップ運営）
- **位置付け**: 国内最大級のAI専門メディア。導入実務（保守費用、予算管理、法務論点等）を扱う記事が多く、Cocolomi顧客の関心領域と直結

### Medium Priority（候補が薄い日に拾う）

#### 4. ITmedia AI＋ ✅
- **URL**: https://www.itmedia.co.jp/aiplus/
- **RSS**: https://rss.itmedia.co.jp/rss/2.0/aiplus.xml
- **形式**: RSS 2.0
- **mainstream**: true
- **対象**: 生成AI、データ分析、コンピューティング、ロボティクス
- **位置付け**: 国内ITメディアの中で最も頻度・速度が高い。技術トレンドとビジネス事例の両方を扱う。海外モデル動向（GPT、Claude、Gemini等）の翻訳・解説も豊富

#### 5. ZDNet Japan ✅
- **URL**: https://japan.zdnet.com/ai/ （AIカテゴリ）
- **RSS**: http://feed.japan.zdnet.com/rss/index.rdf （総合フィード、検証時に最新30本のRDFを取得確認。AIカテゴリ単独RSSは未提供）
- **形式**: RSS 1.0 (RDF)
- **mainstream**: true
- **対象**: エンタープライズ向け記事、海外動向、CIO・CTO層向け論考。AIに限らず総合
- **位置付け**: ITmedia AI+ より企業情報システム視点が強い。Cocolomi顧客（DX推進担当役員等）と接点。**総合RSSのみのため、AI関連はタイトル/カテゴリで絞り込みが必要**（カテゴリURL `/article/.../` のパスから推定するか、タイトルキーワードフィルタ）

#### 6. 日経クロステック（IT領域） ✅
- **URL**: https://xtech.nikkei.com/
- **RSS**: https://xtech.nikkei.com/rss/xtech-it.rdf （IT領域）/ https://xtech.nikkei.com/rss/index.rdf （全領域）
- **形式**: RSS
- **mainstream**: false
- **対象**: 日本企業のIT・DX・AI実装事例、技術解説、業界分析
- **位置付け**: 有料部分多いが**見出しだけでも市場の地殻変動が見える**。導入企業のリアル（成功・失敗）を扱う点で他誌と差別化

### Reference（月1の俯瞰用）

#### 7. DIAMOND Online ✅
- **URL**: https://diamond.jp/
- **RSS**: https://diamond.jp/list/feed/rss/dol
- **形式**: RSS
- **mainstream**: true
- **対象**: ビジネス・経営全般。テクノロジー欄ではAI・DX関連の論考も
- **位置付け**: 企業経営者層の視座でのAI記事を月単位で俯瞰。深掘り解説より時流の話題感を捉える用途

#### 8. 個人情報保護委員会 ⚠️
- **URL**: https://www.ppc.go.jp/news/
- **RSS**: 未提供（一覧ページのみ）
- **形式**: Web Fetch
- **mainstream**: false
- **対象**: 個人情報保護法改正、AI×個人情報のガイドライン、執行事例
- **位置付け**: 生成AI導入時の法的論点（学習データ・出力管理・社員利用）に直結。月1の俯瞰で十分だが、ガイドライン改訂時は High 扱い

#### 9. 情報処理推進機構（IPA） ⚠️
- **URL**: https://www.ipa.go.jp/news/index.html
- **RSS**: 未提供（一覧ページのみ。要追加調査）
- **形式**: Web Fetch
- **mainstream**: false
- **対象**: DXセレクション、暗号鍵管理、セキュリティガイドライン、AI/DX人材育成
- **位置付け**: AIガバナンス・セキュリティの公的指針を捉える。Cocolomi顧客の社内説得材料として機能

---

## Human Energy（企業向け研修）

### High Priority（毎日チェック）

#### 1. 日本の人事部 プロネット ✅
- **URL**: https://service.jinjibu.jp/
- **RSS**: https://service.jinjibu.jp/rss/?mode=news
- **形式**: RSS（ProFuture株式会社運営「プロネット」新着ニュース）
- **mainstream**: true
- **対象**: HRビジネス、人事BPO、調査・統計、書籍紹介、労働法改正
- **位置付け**: 企業研修業界の最頻ハブ。エンゲージメント・採用・労働法改正動向を毎日キャッチ

#### 2. HRpro ⚠️
- **URL**: https://www.hrpro.co.jp/
- **RSS**: 未提供（HTML上に明示なし）
- **形式**: Web Fetch
- **mainstream**: false
- **対象**: 採用、人材育成・研修、人事・労務、システム・業務ツール（ProFuture株式会社運営、日本最大級の人事ポータル）
- **位置付け**: 「日本の人事部」と運営会社が同じだが対象読者は人事担当者寄り。研修手法・組織開発の論考を拾う

#### 3. DIAMONDハーバード・ビジネス・レビュー（DHBR） ⚠️
- **URL**: https://dhbr.diamond.jp/
- **RSS**: 未提供（HTML上に明示なし。サイト全体は無料一部閲覧＋有料/雑誌定期購読モデル）
- **形式**: Web Fetch
- **mainstream**: true
- **対象**: リーダーシップ、イノベーション、戦略、テクノロジー、人材採用・育成（14テーマ）
- **位置付け**: 海外HBRの翻訳記事＋日本独自記事。**「組織開発・カルチャー変革論考」のメインソース**として最重要。研修テーマの理論的深みを補強する役割

### Medium Priority（候補が薄い日に拾う）

#### 4. HRzine ⚠️
- **URL**: https://hrzine.jp/
- **RSS**: 未提供（メールバックナンバー `/ml/backnumber` のみ）
- **形式**: Web Fetch
- **mainstream**: false
- **対象**: HRテック、人事システム、評価制度、組織カルチャー、人的資本経営（翔泳社運営）
- **位置付け**: 翔泳社系のHRメディア。HRテック寄りなので「手法・教育理論として学べる記事」だけ拾う方針（news_profile.md §4.2.2）

#### 5. ITmedia ビジネスオンライン ✅
- **URL**: https://www.itmedia.co.jp/business/
- **RSS**: https://rss.itmedia.co.jp/rss/2.0/business.xml
- **形式**: RSS 2.0
- **mainstream**: false
- **対象**: ビジネストレンド、組織論、リーダーシップ、働き方、人材
- **位置付け**: HRpro/HRzineより「経営層の視点」寄り。研修テーマ→経営課題の翻訳に有用

#### 6. Forbes Japan（リーダーシップ・組織論） ⚠️
- **URL**: https://forbesjapan.com/category/leadership
- **RSS**: 未提供（`/feed`, `/feed/`, `/rss`, `/rss.xml` すべて404確認。HTML内 canonical は `/feed` を指すが実体なし）。代替：sitemap `https://forbesjapan.com/sitemap.xml` → `static.forbesjapan.com/sitemap/sitemap1.xml` 等を解析
- **形式**: Web Fetch（sitemap.xml or HTML一覧スクレイピング）
- **mainstream**: true
- **対象**: リーダーシップ、組織開発、海外経営者インタビュー、企業文化論
- **位置付け**: 海外論者の組織論を翻訳・紹介する役割。DHBRと補完関係。**RSSがないので取得コストが高め**。優先度を Medium → Reference に下げる選択肢あり

#### 7. ProFuture（HRpro/日本の人事部 運営会社） ⚠️
- **URL**: https://www.profuture.co.jp/
- **RSS**: 未提供（独自NEWSセクションあり、HTML一覧 `https://www.profuture.co.jp/` 上に表示）
- **形式**: Web Fetch
- **mainstream**: false
- **対象**: HRテクノロジー大賞アワード運営、HR総研の調査レポート、メディア露出告知（TBS Nスタ等）。月数本ペース
- **位置付け**: HRpro/日本の人事部とは別系統の独自コンテンツ。**業界アワード・統計レポート発表元**として参照価値あり。Reference扱いで十分（更新頻度が低いため）

### Reference（月1の俯瞰用）

#### 8. MIT Sloan Management Review ✅
- **URL**: https://sloanreview.mit.edu/
- **RSS**: https://sloanreview.mit.edu/feed/
- **language**: en
- **形式**: RSS 2.0
- **mainstream**: true
- **対象**: AI、リーダーシップ&カルチャー、戦略、ハイブリッドワーク、変革管理
- **位置付け**: **海外組織論・経営論考の最上位リファレンス**。Responsible AI、AI×ワークフォース等のテーマで一次情報級。差別化の根幹（news_profile.md §4.2.2「現場の本質課題と理論的深みの両端で勝負」）

#### 9. Harvard Business Review（HBR.org） ✅
- **URL**: https://hbr.org/
- **RSS**: http://feeds.hbr.org/harvardbusiness （正しいパスは末尾 `.rss` なし。FeedBurner経由で配信中、検証時にAtom形式で最新エントリ取得確認。`.rss` 付きURLは無応答なので注意）
- **language**: en
- **形式**: Atom
- **mainstream**: true
- **対象**: リーダーシップ、戦略、組織、テクノロジー（英語原文）
- **位置付け**: DHBRの原典。月1の俯瞰で英語記事を直接読み、翻訳前の論考を捉える。**HTTPS版（`https://`）はSSLエラーで未取得。`http://` で運用するか、フェッチ層で証明書エラー耐性を持たせる**

#### 10. Aeon（Psychology / Philosophy） ✅
- **URL**: https://aeon.co/
- **RSS**: https://aeon.co/feed.rss
- **language**: en
- **形式**: RSS 2.0（サイト全体。Psychology単独のカテゴリRSSは無し、タイトル/本文でフィルタ）
- **mainstream**: false
- **対象**: 心理学、認知科学、哲学、神経科学、人間性、文学
- **位置付け**: 研修の理論的バックボーン（認知科学・心理学）を哲学的視座から補強。news_profile.md §4.4 学術領域とも重なる。**カテゴリRSSがないため記事単位の選別が必要**

---

## Web-Repo（フランチャイズ業界）

### High Priority（毎日チェック）

#### 1. PR TIMES フランチャイズタグ ⚠️
- **URL**: https://prtimes.jp/topics/keywords/フランチャイズ
- **RSS**: 未提供（Cocolomi 生成AIタグと同じく、タグ単位のフィードはなし）
- **形式**: Web Fetch（HTML一覧）
- **mainstream**: false
- **status**: rss_unavailable_pending_html_scraper
- **note**: Sprint 3 以降で HTML scraper 実装を検討
- **対象**: 新店出店、FC契約締結、海外展開、加盟店募集、新業態リリース
- **位置付け**: **新規開店・新業態の網羅性が最も高い**。FC本部・加盟者双方の動きを日次で捉える

#### 2. 日経MJ ⚠️
- **URL**: https://www.nikkei.com/special/nikkeimj （特集ページ）/ https://www.nikkei.com/topics/22A00582 （フランチャイズチェーンタグ）
- **RSS**: 未提供（日経電子版の購読者向け配信。日経MJ単独のRSSはなし）
- **形式**: 紙面購読 + Web Fetch（電子版）
- **mainstream**: true
- **status**: rss_unavailable_pending_html_scraper
- **note**: Sprint 3 以降で HTML scraper 実装を検討
- **対象**: 流通・消費・マーケティング全般、FC・チェーンストア、ヒット商品分析
- **位置付け**: 流通系で最も権威ある専門紙（月・水・金発行）。FC業界誌の中で経営判断材料としての価値が最も高い。**有料**だが見出しだけでも変化を察知できる

#### 3. 公正取引委員会 報道発表 ⚠️
- **URL**: https://www.jftc.go.jp/houdou/pressrelease/
- **RSS**: 未提供（公式に提供なし確認済み。トップページ・報道発表ページとも `link rel="alternate"` 不在、フッターにRSSアイコン無し。SNS（X/Facebook/YouTube）連携のみ）
- **形式**: Web Fetch（年度別インデックス → 個別リリース）
- **mainstream**: false
- **status**: rss_unavailable_pending_html_scraper
- **note**: Sprint 3 以降で HTML scraper 実装を検討
- **対象**: 独占禁止法、優越的地位濫用、フランチャイズガイドライン、下請取引、フリーランス法
- **位置付け**: **フランチャイズ業界の規制リスク**を最も早期に捉える。FCガイドライン改訂、優越的地位濫用の摘発事例は事業判断に直結。**スクレイパは「主要報道発表資料(令和N年)」「最近の報道発表資料(令和N年)」のインデックスページから新着を抽出**

#### 4. ビジネスチャンス ✅
- **URL**: https://www.bc01.net/
- **RSS**: https://www.bc01.net/feed/（WordPress 標準、検証時 RSS 2.0 / 58KB / Content-Type: application/rss+xml で取得確認）
- **形式**: RSS 2.0
- **mainstream**: false
- **対象**: フランチャイズ業界専門情報誌、月刊
- **位置付け**: **業界専門誌の中核**。ニッチだが Web-Repo 事業との整合性が最も高い。FC本部・加盟者・業界規制の動向を専門メディアの目線で報じる。Sprint 2 Step C で companies.md Web-Repo High に追加（同時に既存3ソースは HTML scraper 実装待ちとしてマーク）

### Medium Priority（候補が薄い日に拾う）

#### 4. 日本フランチャイズチェーン協会（JFA） ⚠️
- **URL**: https://www.jfa-fc.or.jp/
- **RSS**: 未提供（"WHAT'S NEW" / "プレスリリース" の一覧表示のみ）
- **形式**: Web Fetch
- **mainstream**: false
- **対象**: コンビニ・FC統計、業界ガイドライン、セミナー、海外展示会、環境対策（食品廃棄物・プラスチック等）
- **位置付け**: **業界統計の一次情報源**。月次プレスリリースでコンビニ・FC統計が定期配信される。業界全体トレンドの把握に必須

#### 5. 外食ドットビズ ⚠️
- **URL**: https://gaisyoku.biz/news/ （正しいドメインは `gaisyoku.biz`、`gaishoku` ではない）
- **RSS**: 未提供（HTML一覧のみ）
- **形式**: Web Fetch
- **mainstream**: false
- **対象**: 外食産業の業界ニュース、新規参入、経営動向、チェーンストア統計、インバウンド消費動向
- **位置付け**: 飲食FCの中核情報源。フードリンクと併用で外食FCをカバー

#### 6. フードリンクニュース（FDN） ✅
- **URL**: https://www.foodrink.co.jp/news/
- **RSS**: https://www.foodrink.co.jp/rss.xml
- **形式**: RSS 2.0
- **mainstream**: false
- **対象**: 飲食経営者向け「ホンネ」ビジネスニュース。FC本部・大手チェーンの戦略、新業態、M&A、価格戦略、決算分析
- **位置付け**: **Web-Repo中核読者層（FCオーナー・経営者）と最も近い視座**。1994年創刊、月額1000円の有料部分あり。バーガーキング・サイゼリヤ等の戦略記事の質が高い

### Reference（月1の俯瞰用）

#### 7. 経済産業省 商取引・サービス政策 ✅
- **URL**: https://www.meti.go.jp/policy/economy/distribution/
- **RSS**: 経産省全体のAtom feed `https://www.meti.go.jp/ml_index_release_atom.xml` でカバー
- **形式**: Atom（経産省全体のフィードから商取引関連を抽出）
- **mainstream**: false
- **対象**: フランチャイズ・ガイドライン、流通政策、サービス産業政策
- **位置付け**: Cocolomiの High Priority と同じフィードを共有。FC関連政策の発表は月数件程度なのでReference扱い

#### 8. 中小企業庁 ✅
- **URL**: https://www.chusho.meti.go.jp/
- **RSS**: https://www.chusho.meti.go.jp/rss/index.xml （RSS 1.0/RDF形式、検証時に最新5件取得確認。中小企業庁配下＋経産省プレスのうち中小関連を集約）
- **形式**: RSS 1.0 (RDF)
- **mainstream**: false
- **対象**: 小規模事業者支援、補助金、創業支援、フランチャイズ加盟者保護、事業承継、白書（中小企業白書・小規模企業白書）
- **位置付け**: FC加盟者（小規模事業者）支援策を捉える。**経産省全体フィードと記事重複あり**（一部の記事は `meti.go.jp/press/...` を指す）。重複排除ロジックで `meti.go.jp` ドメインのプレスをマージする想定

#### 9. リセマム（教育FC関連） ✅
- **URL**: https://resemom.jp/
- **RSS**: https://resemom.jp/rss20/index.rdf （RSS 2.0）/ https://resemom.jp/rss/index.rdf （RSS 1.0）
- **形式**: RSS
- **mainstream**: false
- **対象**: 受験、学習教材・塾、英語教育、プログラミング教育、国際教育
- **位置付け**: **教育系FC（学習塾・英会話・プログラミング教室）**の動向を捉える。教育産業はFC業界全体の中で成長分野

#### 10. 東洋経済オンライン ✅
- **URL**: https://toyokeizai.net/
- **RSS**: https://toyokeizai.net/list/feed/rss
- **形式**: RSS 2.0
- **mainstream**: true
- **対象**: ビジネス全般、スタートアップ・新事業、業界分析
- **位置付け**: FC企業の経営分析記事、新業態スタートアップの紹介記事をReference的に拾う

---

## 一次情報URL（参考メモ）

調査過程で収集した、RSS/メタデータ整備の手がかりとなる一次情報URL：

- **ITmedia全RSS一覧**: https://corp.itmedia.co.jp/media/rss_list/ （ITmedia系列の全フィード一覧）
- **日経クロステックRSS配信案内**: https://xtech.nikkei.com/atcl/nxt/info/18/00001/022300009/ （カテゴリ別RSS全件）
- **公正取引委員会 報道発表（年度別）**: https://www.jftc.go.jp/houdou/pressrelease/index.html
- **個人情報保護委員会 改正法特集**: https://www.ppc.go.jp/news/ （改正法ごとの特集ページにリンク）
- **e-Stat 政府統計RSS**: https://www.e-stat.go.jp/rss （統計新着配信、JFA統計と組合せ可能）

---

## 次回セッションのTODO

優先度順：

1. **PR TIMES タグページのスクレイピング設計**（生成AI / フランチャイズ両方共通。タグページHTMLから記事リスト抽出するパーサ。`fetch.py` のSourceドライバ抽象化と並走させる）
2. **ノイズフィルタの設計**（PR TIMES生成AIタグのノイズ問題、配信元企業ホワイトリスト/ブラックリスト方針。FCタグも同様の設計が要る）
3. **Aeon の記事単位フィルタ設計**（カテゴリRSSがないため、Psychology/Cognition/Philosophyタイトルのキーワード判定が必要）
4. **ZDNet Japan総合RSSのAI絞り込み**（カテゴリ専用RSSがないため、`/article/` パスから記事ページを取得しbreadcrumb/categoryメタを抽出するか、タイトルキーワードで判定）
5. **HBR.org のHTTPS問題対応**（`http://feeds.hbr.org/harvardbusiness` で運用するか、フェッチ層でSSL証明書緩和オプションを持たせるか判断）
6. **Forbes Japan の sitemap 解析設計**（RSSなし確定。`sitemap1.xml`/`sitemap2.xml` から記事URLを抽出し、最終更新日でソートして直近分のみ取得する設計）
7. **重複排除ロジック**（特に経産省フィード ↔ 中小企業庁フィードのオーバーラップ）

---

**文書バージョン**：v0.3
**作成日**：2026/4/27（月曜夜セッション）
**更新履歴**：
- v0.1（2026/4/27）：初版作成、28ソース整備（✅9件、⚠️12件、❌7件）
- v0.2（2026/4/27）：❌7件の再調査完了。RSS確定3件追加（Aeon、フードリンクニュース、中小企業庁）、URL候補確定3件（HBR.org、Forbes Japan、外食ドットビズ）、ZDNet Japanは Japan版RSS不在を確認
- v0.3（2026/4/26）：未検証6件の最終検証完了。✅追加4件（HBR.org `/harvardbusiness`、ZDNet Japan総合RSS `feed.japan.zdnet.com/rss/index.rdf`、中小企業庁、ProFuture独自NEWS）。RSS未提供確定2件（Forbes Japan、公正取引委員会）。HBR.orgの正しいパスは末尾 `.rss` なし、HTTPS版は SSL_ERROR_SYSCALL でHTTPのみ動作

**次回見直し**：`fetch.py` 設計時、または1週間運用後
