# Academic — 学術領域（人文学・認知科学）の情報源

このファイルは Kamiyama Tribune **第4面 Arts & Letters（学術ニュース・「今週の概念」コラム）** の情報源リストである。
神山さんの関心三領域（**現象学 / 認知言語学 / 暗黙知の形式知化**）と重要論者（**竹田青嗣・野矢茂樹・野中郁次郎・國分功一郎**）に紐づくソースを、**ウォッチ優先順位（高 / 中 / 低）×ソース** のマトリクスで記録する。

選定の方針は `news_profile.md` §4.4 を参照。Tribune全体の選定基準は同文書 §3 の美意識7項目と §5 の横断ルール。**学習段階は入門〜中級**、専門論文より **解説・概説・架橋する論考** を優先すること。**「他者の認知をどう共有できると考えるか」**（§4.4 隠れた中核問い）を意識し、現象学×仏教、認知科学×質的研究 のような **学問領域を架橋する記事** を高評価する。

**ステータス凡例**：
- ✅ 検証済み（フィード/URLが実際に取得できることを確認）
- ⚠️ 一部未検証（URLは到達するが、フィード形式・更新頻度・カテゴリ分けは要追加調査、または公式RSS不在で代替手段で運用）
- ❌ 未検証（時間切れ、または取得エラー。次回セッションで再調査）
- 🔗 既出ソース（他ファイルで詳細登録済、本ファイルでは学術観点で再参照）

**領域全体の特徴**：国内人文学系の出版社サイトは **note.com 移行**（WEBちくま等）や **RSS廃止**（青土社等）が進行中。学会・学術機関のサイトは多くが **静的HTML時代の構成のまま** で、RSSはほぼ皆無。対照的に **英語圏の学術メディアは RSS が現役**（Stanford SEP・Philosophy Now 等）、しかし PhilPapers のように bot 対策で閉ざされる例も増加。

---

## 国内出版社・新書系（毎日チェック）

### 1. 集英社新書プラス ✅
- **URL**: https://shinsho-plus.shueisha.co.jp/
- **RSS**: https://shinsho-plus.shueisha.co.jp/feed
- **形式**: RSS 2.0（WordPress 標準）
- **mainstream**: true
- **対象**: 集英社新書のWebメディア。新刊紹介、著者対談、Web連載エッセイ
- **位置付け**: **國分功一郎の常連寄稿先**（『暇と退屈の倫理学』『中動態の世界』等）。news_profile.md §4.4 設計方針「**國分功一郎の新刊・対談・発言は確実に拾う**」の最重要ソース。集英社新書は **入門〜中級レベルの解説書** が多く、§4.4 学習段階方針と整合

### 2. 春秋社 ✅
- **URL**: https://www.shunjusha.co.jp/
- **RSS**: https://www.shunjusha.co.jp/rss/news/（**異色パス、`/feed` は 404**、2026-04-23 lastBuildDate）
- **形式**: RSS 2.0
- **mainstream**: false
- **対象**: 春秋社の新刊・お知らせ。**仏教・哲学・心理学が看板領域**
- **位置付け**: news_profile.md §4.4 関心領域(i) 現象学の「**仏教との共通点に関心**」に最も合致する出版社。仏教×現象学、東洋思想×哲学の架橋本を多数刊行。**`/rss/news/` の異色パスはフェッチ層に明示登録必須**（cooking.md cookpad と並ぶ事例、本ファイルで4件目の「異色RSSパス」）

---

## 国内出版社・思想誌（Medium）

### 3. 青土社（現代思想） ⚠️
- **URL**: https://www.seidosha.co.jp/
- **RSS**: **未提供**（`/feed` 404、HTML内 RSS リンクなし）
- **形式**: HTML スクレイピング
- **mainstream**: true
- **対象**: 月刊『現代思想』『ユリイカ』を発行。**現象学・精神分析・哲学・批評** の特集号が定期刊行
- **位置付け**: **国内思想誌の最重要ハブ**。『現代思想』の **特集号テーマ**（例：現象学の現在、メルロ＝ポンティ、ユクスキュルと環世界 等）は §4.4 関心三領域に直撃する。RSS不在は痛いが、月1ペースの特集発表をスクレイピング監視で十分捕捉可能。Medium 扱いだが特集号テーマ次第で High 昇格

### 4. WEBちくま ❌
- **URL**: https://www.webchikuma.jp/ → **`webchikuma.com` に移行 → note.com パスワードゲート**にリダイレクト
- **RSS**: **取得不可**（複数段階のリダイレクト後、note.com の閉鎖セッションに到達。プログラマティック取得不可）
- **形式**: ❌
- **mainstream**: false
- **対象**: 筑摩書房Web連載。野矢茂樹・國分功一郎・竹田青嗣 等の連載・対談記事
- **位置付け**: **本来は §4.4 重要論者の最重要寄稿先** だったが、サイト移行＋note.com の認証ゲートで取得不可。代替候補として **筑摩書房 公式お知らせページ**（`https://www.chikumashobo.co.jp/`）を次回 TODO で検証。失敗事例として記録、フェーズ2で再調査必須

---

## 国内学会・学術機関（Reference）

### 5. 日本認知科学会 ❌
- **URL**: https://www.jcss.gr.jp/
- **RSS**: **未提供**（`/feed`、`/feed/` ともに 404、サイトは静的HTML時代の構成）
- **形式**: ❌
- **mainstream**: false
- **対象**: 認知科学会誌・大会発表・若手の会等の学術活動
- **位置付け**: news_profile.md §4.4 関心領域(ii) 認知言語学・(iii) 暗黙知の **学会一次情報源**。RSS不在のため、**代替として CiNii Articles（`https://cir.nii.ac.jp/`）の認知科学キーワード検索 RSS**、**J-STAGE 認知科学誌**（`https://www.jstage.jst.go.jp/browse/jcss/`）の検証を次回TODO化。学会公式は望み薄

---

## 国際（哲学・人文学）

### 6. Aeon ✅
- **URL**: https://aeon.co/
- **RSS**: https://aeon.co/feed.rss
- **language**: en
- **形式**: RSS 2.0（サイト全体）
- **対象**: 心理学・認知科学・哲学・神経科学・人間性・文学を架橋する英語エッセイ
- **位置付け**: news_profile.md §4.4 関心領域 (i) 現象学・(ii) 認知科学を **英語圏の一般読者向けエッセイで深める** 用途。Aeon Psychology / Philosophy カテゴリは入門〜中級者向けに学問領域を架橋する記事を提供（例：「Yorùbá の世界観は意識をどう捉えるか」「ユクスキュルの環世界と現代の精神医学」）。C36 Step 2a (2026-06-05) で academic.md primary 化、page4 fetch 経路へ到達可能にした（旧 cross-ref 構成では見出しに含まれる "Reference #N" が parser に Priority.REFERENCE 切替と誤認識されて entry 自体が dropped されていた）

### 7. Philosophy Now ✅
- **URL**: https://philosophynow.org/
- **RSS**: https://philosophynow.org/rss
- **language**: en
- **形式**: RSS 2.0（隔月刊誌、現在号の記事を配信）
- **mainstream**: true
- **対象**: 英国の哲学雑誌。**入門〜中級者向けの哲学入門** に定評、フッサール・メルロ＝ポンティ・哲学者特集号が定期刊行
- **位置付け**: §4.4 学習段階方針「**入門〜中級**」と最も整合する英語哲学誌。Stanford SEP が「百科事典」、PhilPapers が「論文」とすれば Philosophy Now は **「読み物としての哲学」**。神山さんの嗜好（**学問領域を架橋する論考**、§4.4 設計方針）に最適

### 8. Stanford Encyclopedia of Philosophy（SEP） ✅
- **URL**: https://plato.stanford.edu/
- **RSS**: https://plato.stanford.edu/rss/sep.xml（新項目・改訂項目通知）
- **language**: en
- **形式**: RSS 2.0
- **mainstream**: true
- **対象**: スタンフォード大学運営の **哲学百科事典**。専門家による項目別の包括的解説。新項目追加・既存項目改訂の通知 RSS
- **位置付け**: **概念単位での深掘り** が必要な「**今週の概念」コラム**（本紙第4面、design_spec.md）の **構造的バックボーン**。新項目通知 RSS により「現象学」「環世界」「中動態」「暗黙知」等のコラムテーマ候補が **学術的お墨付き付き** で得られる。Reference 扱いだがコラム制作時には High 化

### 9. The Marginalian 🔗（既出：books.md Reference #13）
- **URL**: https://www.themarginalian.org/
- **RSS**: https://www.themarginalian.org/feed/
- **language**: en
- **学術観点での位置付け**: マリア・ポポバの **科学・哲学・文学の交差** エッセイ。news_profile.md §4.4 設計方針「**学問領域を架橋する論考を高評価（現象学×仏教、認知科学×質的研究等）**」を **個人エッセイの形** で実現するソース。ポパー・クーン等の **科学哲学** 系エッセイは §4.5.4「未踏だが関心高（朝刊が入り口提案を担う）」枠とも重複。**詳細は `books.md` を参照**

### 10. PhilPapers ❌
- **URL**: https://philpapers.org/
- **RSS**: **未検証完了**（`/feed/` 403、ブラウザUAでも 403、Cloudflare 系 bot 対策で完全閉鎖）
- **language**: en
- **形式**: ❌
- **mainstream**: false
- **対象**: 哲学論文・書籍の総合インデックス（学術検索データベース）
- **位置付け**: 本来は **論者別フォロー**（フッサール研究、野中郁次郎の海外受容、中動態論等の最新論文）に最適だったが、配信インフラが閉鎖。代替候補として **PhilArchive**（`https://philarchive.org/`、PhilPapers の論文プレプリントサーバ）の検証、または **OpenAIRE**（EU の学術メタデータAPI）の活用を次回TODO

---

## 国際・人文評論誌（High Priority — C36 Step 2b 多様化, 2026-06-09 追加）

**背景**：C36 Step 1 で 4 日連続 The Marginalian 独占、集英社新書プラス 82% の偏重を確認。Step 2a で構造バグを 4 件修復したが、**ソース母集団が薄い** という構造的限界が残存。Step 2b は英語ソース 5 件を High Priority で投入し、ローテーションプールを実質倍化する。**page4 academic 描画に翻訳経路を追加**（regen_front_page_v2.py の `build_page_four_v2` → `translate_for_render`、Sprint 5 ポリシーに従いタイトルのみ翻訳）。

### 11. 3 Quarks Daily ✅
- **URL**: https://3quarksdaily.com/
- **RSS**: https://3quarksdaily.com/feed
- **language**: en
- **形式**: RSS 2.0（WordPress 標準）
- **mainstream**: false
- **対象**: 科学・哲学・文学・芸術・政治を横断するエッセイ集積サイト。月曜は編集部執筆、火〜日は外部記事のキュレーション
- **位置付け**: news_profile.md §4.4 設計方針「**学問領域を架橋する論考を高評価**」と最も整合する英語サイトの一つ。Aeon と並走させることで「**領域横断エッセイ**」枠を 2 媒体体制にできる。フェッチ頻度高め（毎日 5-10 本）

### 12. Public Books ✅
- **URL**: https://www.publicbooks.org/
- **RSS**: https://www.publicbooks.org/feed/
- **language**: en
- **形式**: RSS 2.0（WordPress 標準）
- **mainstream**: false
- **対象**: NYU・ハーバード系の学者ネットワークが運営する **学術寄り書評誌**。社会学・歴史学・文学批評の長尺レビュー
- **位置付け**: §4.4 「学問領域を架橋する論考」の **書評形式版**。NYRB より学術寄り、LRB と並ぶ重量級書評誌。集英社新書プラスの国内書評枠を **海外学術書評で補完**

### 13. The Point Magazine ✅
- **URL**: https://thepointmag.com/
- **RSS**: https://thepointmag.com/feed/
- **language**: en
- **形式**: RSS 2.0（WordPress 標準）
- **mainstream**: false
- **対象**: シカゴ大学院生グループ発の **思想・批評誌**。哲学・政治・文化を扱う長尺エッセイ
- **位置付け**: §4.4 「現象学」「認知科学」「暗黙知」の周辺領域（実存・倫理・公共哲学）を **若手研究者の視点** で扱う媒体。Philosophy Now が「百科事典寄り」、The Point は「**現代思想の現在進行形**」

### 14. n+1 ✅
- **URL**: https://www.nplusonemag.com/
- **RSS**: https://www.nplusonemag.com/feed/（**`www.` なし URL は 301 リダイレクト、canonical は `www.` 付き**）
- **language**: en
- **形式**: RSS 2.0（WordPress 標準）
- **mainstream**: false
- **対象**: NY 発の文芸・思想誌。文学・批評・政治を扱う長尺エッセイ、書評、フィクション
- **位置付け**: NYRB / LRB が「権威系書評」とすれば n+1 は「**ポスト LRB 世代の文芸誌**」。§4.4 周辺領域（文学・批評）を補強。配信頻度は中程度（週 3-5 本）

### 15. London Review of Books（LRB） ✅
- **URL**: https://www.lrb.co.uk/
- **RSS**: https://www.lrb.co.uk/feeds/rss
- **language**: en
- **形式**: RSS 2.0
- **mainstream**: true
- **対象**: 隔週刊の英国書評誌。文学・歴史・政治・哲学の長尺書評で世界的に著名
- **位置付け**: NYRB 並の権威書評誌、配信は隔週刊だが 1 号あたり 20 本前後のレビュー。NYRB が WordPress 標準 `?post_type=article` クエリで運用しているのに対し、LRB は標準 RSS で素直に取得可能。**書評ジャンルの本命枠**

---

## 一次情報URL（参考メモ）

調査過程で収集した、RSS/メタデータ整備の手がかりとなる一次情報URL：

- **筑摩書房 公式お知らせ**: https://www.chikumashobo.co.jp/news/ （WEBちくま代替候補、次回検証）
- **岩波書店 編集部 X**: 新書・全集の最新刊告知（フェーズ2でRSS化）
- **CiNii Articles 検索 RSS**: https://cir.nii.ac.jp/articles?q=現象学&sortorder=1&format=rss （キーワード単位で論文取得可能）
- **J-STAGE 認知科学誌**: https://www.jstage.jst.go.jp/browse/jcss/ （新刊号RSS検証要）
- **note.com 個人著者フォロー**: 國分功一郎・斎藤幸平 等の note アカウントは個別フィード `https://note.com/{user}/rss` で取得可能
- **PhilArchive（PhilPapers プレプリント）**: https://philarchive.org/ （PhilPapers代替検証候補）
- **野中郁次郎 一橋ICS**: https://www.ics.hub.hit-u.ac.jp/ （一橋国際企業戦略研究科、知識創造論の本拠地）

---

## 次回セッションのTODO

優先度順：

1. **WEBちくま 代替の確立** — `chikumashobo.co.jp/news/` のRSS / スクレイピング検証。野矢茂樹・國分功一郎の寄稿が拾えなくなるのは致命的、Phase 1 完了前に必須対応
2. **note.com 著者フィード活用** — 國分功一郎・斎藤幸平・哲学系研究者の note RSS（`https://note.com/{user}/rss` パターン）を **論者別フォロー** として集約。WEBちくま閉鎖の補填にも
3. **CiNii Articles キーワードRSS** — 認知科学会の RSS が無いため、CiNii の **「現象学」「暗黙知」「中動態」** 等のキーワード検索 RSS で論文発表を捕捉。`?format=rss` パラメータで取得可能
4. **PhilArchive の検証** — PhilPapers の代替プレプリント・サーバ。bot 対策の有無、RSS提供有無を確認
5. **「今週の概念」コラム素材リストの整備** — Stanford SEP の新項目通知 RSS をベースに、§4.4 関心三領域に該当する項目（現象学、認知言語学、暗黙知、中動態、環世界 等）の **概念リスト** を `concepts.md` に列挙（フェーズ2、roadmap.md §3.2 の「今週の概念コラム自動生成」と接続）
6. **学術領域横断の重複排除** — Aeon（companies.md）・The Marginalian（books.md）・本ファイルの Stanford SEP / Philosophy Now で **同じ哲学者・概念** が同時期に扱われるパターンが頻出。**論者名 + 概念名** での重複検知
7. **「他者の認知をどう共有できると考えるか」フィルタ**（§4.4 隠れた中核問い） — 他領域に波及させない方針のため、本ファイルのソース内でのみ **間主観性・本質直観・現象学的還元・暗黙知共有** 等のキーワードに高スコア付与する選定ロジック（フェーズ2、§4.4 設計方針の核心）

---

**文書バージョン**：v0.1
**作成日**：2026/4/27（火曜夜セッション）
**更新履歴**：
- v0.1（2026/4/27）：初版作成、10エントリ整備（ユニーク8件 + 既出再参照2件、ユニーク内訳：✅4件、⚠️1件、❌3件）。**WEBちくま閉鎖が痛打**、`chikumashobo.co.jp/news/` 検証と note.com 著者フィード活用を次回必須対応に。春秋社は異色パス `/rss/news/`、フェッチ層の永続化が次回TODO

**次回見直し**：`fetch.py` 設計時、または WEBちくま代替検証完了時
