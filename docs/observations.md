# Tribune 観察事項リスト

## このファイルについて

Tribune の運用中に神山さんが発見した改善点・違和感・将来の Sprint 候補を
体系的に記録する。Code が新しい Sprint 着手時に **前提情報** として参照する場所。

### 位置づけ

- `docs/themes.md` が「テーマプール」、`data/monthly_pivotal.json` が
  「週次選定の結果」なら、本ファイルは **「運用フィードバックの貯水池」**
- 朝刊レビュー時に「これ気になる」と思ったことを軽くメモする場所
- 月次レビュー / Sprint 着手判断時に Code が一括参照

### 更新ルール

- 新規観察は「未着手」セクションに追記
- Sprint 着手で「進行中」へ移動、完了で「完了」へ移動
- 各エントリには **発見日 / 観察内容 / 検討案 / Sprint 候補 / 関連 commit / 状態** を記録
- 該当 commit が無い段階では `-` のままで OK
- 神山さんの自由追記欄として各エントリ末尾に余白を残す

### 既存 ID 系列との関係

- Code 着手案件番号（C36 / C42 / …）は **着手時に振られる連番**
- 観察事項は着手前の段階を含むため、本ファイルでは **見出しで識別**
  し、関連する C 番号があれば「関連 commit」欄で参照する

---

## 未着手









### Sprint 11 候補（既存・神山さん管理）

下記は神山さん管理の Sprint 11 候補項目。詳細内容は神山さん追記待ち。

-
*C70/C71 は C125 で対応、完了セクション参照*

---

## 進行中

（現時点でなし）

---

## 完了

### QUE 採用ゼロ継続 → 誤認識訂正で完結

- **発見日**: 2026-06-29
- **観察当初**: QUE（新潮 QUE）の採用が W5 期間（6/21-27）から
  W6 Day 1-2（6/28-29）までゼロ続きとの認識
- **C110 真因究明**（2026-06-30）:
  - Sprint 9 (5/24-6/13, 21 日): QUE 採用 2 件、0.10/日
  - Sprint 10 (6/14-6/29, 15 日): QUE 採用 4 件、**0.27/日**（2.7 倍）
  - 「9 日間ゼロ」は誤認識、日次ばらつきが激しいだけで構造的問題なし
- **状態**: 完了（修正不要）
- **関連 commit**: C110 調査結果報告のみ

### C70 books カテゴリ偏り (Paris Review 50% 占有) + C71 music カテゴリ偏り (natalie.mu 63% 占有) → 完了

- **発見日**: 神山さん管理の Sprint 11 候補、C121-C123 と同パターンで消化
- **観察当初**:
  - books: The Paris Review (#5) が過去採用の 50% 占有、神山さんの多様な
    文学関心（現代英米文学 / 翻訳文学 / ノンフィクション横断）に対して
    供給偏り
  - music: ナタリー音楽 (#6) が過去採用の 63% 占有、海外インディー・
    フェス関連の供給不足（The Quietus は WAF 遮断で ❌、Pitchfork は
    Reference で日次頻度低い）
- **C125 実装**（2026-07-04）:
  - 4 RSS 探索、両方の追加候補が RSS 完全動作:
    - **LitHub (Literary Hub)** `lithub.com/feed` — 200 OK,
      application/rss+xml, items 10, 7/2 直近更新
    - **Stereogum** `stereogum.com/feed` — 200 OK,
      application/rss+xml, items 40, 7/3 直近更新
    - The Millions / Mikiki: Content-Type text/html で RSS 不成立
    - NPR Music: 403 遮断
    - OTONANO: 全 000
  - `sources/books.md` 海外純文学 Medium に `#7 Literary Hub ✅` 追加。
    Paris Review (#5, 作家インタビュー最高峰) との分担で日次総合媒体
    として補完
  - `sources/music.md` 海外ロックメディア Reference に `#12 Stereogum ✅`
    追加。The Quietus (#11 ❌) の閉鎖代替候補として正式格上げ、
    Pitchfork (#10) との分担で日次インディー・フェス情報を強化
- **動作確認**:
  - `python3 -m scripts.fetch --source "Literary Hub" --limit 3`:
    3 記事取得成功（What to read next based on your favorite A24 movie /
    Independent Press Top 40 / Am I the Asshole）
  - `python3 -m scripts.fetch --source "Stereogum" --limit 3`:
    3 記事取得成功（Michael Stipe & Brandi Carlile カバー / Touch & Go
    創業者訃報 / Julian Casablancas Oxford 講演）
  - 主要 7 testsuite regression: 172/172 pass
- **想定効果**:
  - books: Paris Review 一極を緩和、日次総合文学媒体で英米中心の広い供給
  - music: ナタリー独占を緩和、海外インディー・フェス関連の日次配信
    （神山さんのフェス関心と整合）
- **状態**: 完了
- **関連 commit**: C125

### W5 Day 4 表題と本文のロジック不整合 → 完了

- **発見日**: 2026-06-24（W5「環世界」Day 4 朝刊レビュー）
- **観察当初**: 1 面日付論考の階層 2 タイトル (daily_question) が本文
  主題を正確に表現していない。特に対立構造を扱う週で「主題」と「対比
  対象」を混同する
  - 実例（W5 Day 4）:
    - 表題: 「『別の知覚』を許容しない思想の系譜とは何か？」
    - 本文: ユクスキュル / フーコー / ドゥルーズ / 和辻など「別の知覚
      に価値を見出した側」が主体、デカルト（不許容側）は対比対象 1 名
      のみ
    - 正しい表題例:「『別の知覚』に価値を見出した思想の系譜」
      「『正常性』への批判の系譜」
- **C124 実装**（2026-07-04）:
  - 発生源特定: `scripts/page1_v3/prompts.py` の `ESSAY_SYSTEM_PROMPT`
    において、`daily_question` の生成指針が「20-30 字の問い、当日の
    角度を象徴する一文」だけで弱く、対立構造を扱う際の主題/対比対象の
    区別ルールが無かった
  - 修正: `ESSAY_SYSTEM_PROMPT` の JSON 出力形式の直前に新セクション
    「【daily_question の絶対ルール】★ C124 W5 Day 4 の混同事故防止」
    を追加:
    - 「主題」= 論考が肯定/主張/価値を認めるもの
    - 「対比対象」= 論考が批判/相対化/前提を疑うために引き合いに出すもの
    - 対立構造では **必ず本文の主題側** を問いの主語に据える
    - 悪い例（W5 Day 4 実例）+ 良い例（主題側を主語にした問い）を明示
    - 検証手順「問いの主語 = 本文の中心的主体か？」を LLM に要求
- **動作確認**:
  - プロンプト展開: 新セクション 800 chars 追加、位置 1063 (JSON 出力
    ルールの直前)
  - 主要 6 testsuite regression: 135/135 pass
  - 実 LLM 呼び出しは API キー要のため未実行、明朝 (7/5) cron 以降の
    実紙面で神山さん判断
- **想定効果**:
  - 対立構造を扱う週（W5 環世界、次に来る類似テーマ）で階層 2 タイトル
    が本文主題に忠実に生成される
  - 表題「〜を許容しない/否定する思想」型の混同が構造的に消える
  - editorial 本文には影響なし（表題のみの修正）
- **7/5 朝以降の効果確認予定**（神山さんレビュー）:
  - 対立構造を含む論考で表題が本文主体と一致するか
  - W7「フラット組織の限界」（Aeon 良い階層 vs 悪い階層）でも効果検証
    可能
- **状態**: 完了
- **関連 commit**: C124

### 第 6 面 ハイク欄の UL 偏り（記事側ソース）→ 部分完了（BE-PAL 追加、追加候補は parser 対応後）

- **発見日**: 2026-06-18（朝刊レビュー、C117 でコメント側 UL バイアス
  緩和は済）
- **観察当初**: 記事側ソースが UL（山と道・ハイカーズデポ系）に偏り、
  キャンプ・自然観察・自然文化系の RSS 実運用ゼロ。C117 でコメント側は
  緩和済だが記事側の多様化は別課題
- **C123 実装**（2026-07-04）:
  - 現状分析: UL/縦走系 (Backpacking Light / Section Hiker / CleverHiker
    / The Trek) と海外総合 (Atlas Obscura / Outside / Backpacker) は
    RSS 動作、日本語キャンプ・自然系はハピキャン ⚠️ のみで RSS 未提供
  - 4-7 サイト調査で以下の RSS 動作を確認:
    - **BE-PAL** (`bepal.net/feed`) — 小学館、200 OK、WordPress RSS 2.0
    - CAMP HACK (`camphack.nap-camp.com/feed`) — 200 OK だが XML
      unbound prefix parse エラー
    - ナショナル ジオグラフィック日本語版 — 200 OK だが XML not
      well-formed
    - 好日山荘マガジン — 200 OK だが XML not well-formed
    - 他候補（TABI LABO / Camp in Japan / ソトシル 等）は範囲不整合
  - `sources/outdoor.md` に `#14 BE-PAL ✅`（国内キャンプ・自然情報 Medium）
    を追加。CAMP HACK / NatGeo日本 / 好日山荘は「候補メモ」として
    parser 強化後の再検討候補として outdoor.md 内に記録
- **動作確認**:
  - fetch CLI dry-run: BE-PAL 3 記事取得成功:
    - [2026-07-04] Snow Peak × URBAN RESEARCH DOORS の別注 T シャツ
    - [2026-07-03] 業務スーパーの冷凍魚介
    - [2026-07-03] TOKYO CRAFTS 新作ギアでキャンプサイト快適アップデート
  - 主要 7 testsuite regression: 172/172 pass
- **想定効果**:
  - 6 面ハイク欄に日本語キャンプ・野遊び記事が日次流入
  - UL 系（山と道・ハイカーズデポ系）と BE-PAL（大人の野遊び）で
    ローテーション、C117 のコメント緩和と併せて UL 偏りが構造的に解消
- **持ち越し**:
  - CAMP HACK / NatGeo日本 / 好日山荘 は RSS driver 側の XML parser
    強化（tolerant parser / namespace 対応強化）後の再挑戦候補
- **状態**: 部分完了（BE-PAL 追加で当初目的の 6 面 UL 偏り緩和は達成、
  追加ソースは parser 対応後）
- **関連 commit**: C123

### Web-Repo 事業ドメイン「フィットネス系」業界ニュース未カバー → 完了

- **発見日**: 2026-07-04（C121 実装時に判明、当日 C122 で解決）
- **観察当初**: Web-Repo のフィットネス事業領域が未カバー。C121 で
  買取・飲食は RSS で追加できたが、Fitness Business
  (https://business.fitnessclub.jp/) は RSS 未提供
- **C122 実装**（2026-07-04）:
  - サイト構造調査:
    - robots.txt: `/articles/-/*` と `sitemap.xml` は許可、Disallow は
      `/search/` / `/category/seminar|tour|data/` のみ
    - sitemap.xml に article URL 2424 件、ただし `<lastmod>` 無し
    - 個別記事に JSON-LD Article schema あり
      （`datePublished` / `description`）
    - 有料 wall のため本文全文は取れないが meta description で冒頭
      100-200 字取得可
  - `scripts/lib/drivers/fitness_business.py` 新規実装:
    - `FitnessBusinessDriver(HtmlScrapeDriver)` サブクラス、
      `HOST = "business.fitnessclub.jp"`
    - sitemap.xml → `/articles/-/{ID}` 抽出、lastmod あれば降順、
      無ければ article ID 降順 fallback（初回実装で lastmod あり想定
      が実運用では ID 降順のみ動作、テスト側で両ケースをカバー）
    - 個別記事 → JSON-LD Article schema と meta description から
      title / pub_dt / body 抽出、3 段 fallback（JSON-LD → h1 →
      `<title>` の "| Fitness Business" suffix 剥がし）
  - `scripts/fetch.py` dispatch loop に FITNESS_BUSINESS_HOST 分岐追加
    （QUE / JFTC と同パターン）
  - `tests/test_fitness_business.py` 新規（15 tests: sitemap parse
    ×3 / article parse ×7 / 定数 sanity ×2 / 各種 fallback）
  - `sources/companies.md` Web-Repo Reference 群直前に `#9 Fitness Business ✅`
    追加
- **動作確認**:
  - Unit tests: 15/15 pass
  - 主要 7 testsuite regression: 168/168 pass
  - fetch CLI dry-run: 3 記事取得成功:
    - [2026-07-03] AI 姿勢分析「Sportip Pro」SPORTEC2026 出展
    - [2026-07-02] アイレクススポーツライフ「ILEX AI GYM 24」豊橋駅開業
    - [2026-07-02] メディカルフィットネス・フォーラム 2026 参加申込受付
- **想定効果**:
  - Web-Repo フィットネス事業領域が日次カバー
  - C121 の買取・飲食追加と合わせて 3 領域完成
  - 「ビジネスチャンス」偏重の完全解消
- **状態**: 完了
- **関連 commit**: C122

### 第 2 面 Web-Repo 業界ニュースの「ビジネスチャンス」偏り → 部分完了（買取・飲食追加、フィットネスは別案件持ち越し）

- **発見日**: 2026-06-18（朝刊レビュー、複数回再発）
- **観察当初**: Web-Repo（フランチャイズ業界）向けソースが「ビジネス
  チャンス」型に偏っている。事業領域「飲食・外食 / フィットネス / 買取」
  のうち買取・フィットネスがゼロ、飲食も一部（フードリンクニュースのみ）
- **C121 実装**（2026-07-04, Sprint 11 第 2 案件）:
  - 現状分析: Web-Repo High Priority に PR TIMES / 日経MJ / 公取委
    (C120 で ✅ 化) / ビジネスチャンス、Medium にフードリンクニュース、
    Reference に経産省・中小企業庁・リセマム・東洋経済
  - 3 領域の業界メディア調査で RSS 提供確認:
    - 買取・リユース: **リユース経済新聞**（`/rss` で 200 OK、RSS 2.0）
    - 飲食・外食: **食品新聞 WEB版**（`/feed/` で 200 OK、WordPress RSS）
    - フィットネス: **Fitness Business** 発見も RSS 未提供 → 別案件へ
  - `sources/companies.md` Web-Repo Medium に 2 追加（#7 リユース経済
    新聞、#8 食品新聞 WEB版）
- **動作確認**:
  - `python3 -m scripts.fetch --source "リユース経済新聞" --limit 3`:
    3 記事取得成功（韓国古着卸 / イオシス物流拠点 / RINKAN 初任給）
  - `python3 -m scripts.fetch --source "食品新聞" --limit 3`:
    3 記事取得成功（フレイル予防サービス振興会 / ライフ「ビオラル」10 周年
    / フジ トレー無地化）
- **想定効果**:
  - 買取・リユース事業ドメインの直接業界ニュースが日次流入
  - 飲食業界の網羅性が向上（フードリンクの FC 経営者視座 + 食品新聞の
    業界全体視座で分担）
  - 「ビジネスチャンス」偏重の解消に寄与
- **持ち越し**: フィットネス系（別案件、「Web-Repo 事業ドメイン
  『フィットネス系』業界ニュース未カバー」として未着手セクションに
  記録）
- **状態**: 部分完了（買取・飲食完了、フィットネス持ち越し）
- **関連 commit**: C121

### 日本フランチャイズチェーン協会 (JFA) の scraper 未実装 → 完了

- **発見日**: 2026-07-08 朝刊レビュー
- **観察当初**: 7/8 朝刊 Web-Repo 枠で JFA 記事が pick されたが表示は
  「[scraper not implemented] 日本フランチャイズチェーン協会（JFA）」+
  「RSS unavailable. Add a per-site HtmlScrapeDriver subclass」
- **背景**: JFA は Web-Repo の一次ソース（FC 統計・規制ガイドライン・
  業界団体公式発表）。C120 公取委と同性質で事業直結度高い
- **C127 実装**（2026-07-09）:
  - サイト構造調査:
    - robots.txt: Amazonbot / Perplexity / cohere-ai / Bytespider 等
      AI クローラを個別 Disallow、汎用 UA は OK
    - sitemap.xml: 2013 年で更新止まっている（静的ダミー）→ 使えない
    - プレスリリース一覧 `/lpcarticle/release/1`: `<dl class="newsList">`
      に `<dt>YYYY.MM.DD</dt><dd><h2><a href="URL">タイトル</a></h2></dd>`
      の DL ペア構造
    - 個別記事 `/particle/{ID}.html`: 本文構造弱い（h1 空 / mainCtt div
      のみ / meta description 汎用）
  - `scripts/lib/drivers/jfa.py` 新規実装（**HTTP 1 回で完結の軽量設計**):
    - `JfaDriver(HtmlScrapeDriver)`, `HOST = "www.jfa-fc.or.jp"`,
      `LIST_URL = /lpcarticle/release/1`
    - Public: `parse_list_page(html)` / `_parse_ymd_dot(s)`
    - 個別記事ページは叩かない（本文取得困難 + Stage 1/2 評価には
      title + source_name で十分の判断）
    - description は `"日本フランチャイズチェーン協会プレスリリース: <title>"`
      で Stage 1 の 30 字フィルタ通過を確保
  - `scripts/fetch.py` dispatch loop に JFA_HOST 分岐追加
    （QUE / JFTC / Fitness Business と同パターン）
  - `tests/test_jfa.py` 新規（12 tests: 日付 parse × 3 / list parse × 5 /
    定数 sanity × 2 / 空 HTML 処理）
  - `sources/companies.md` の JFA entry: ⚠️ → ✅、fetch_method: Web Fetch
    → HTML、実装内容明記
- **動作確認**:
  - Unit tests: 12/12 pass
  - fetch CLI dry-run:
    - [2026-06-22] コンビニエンスストア統計調査5月度
    - [2026-06-02] 「まちの安全・安心ステーション東京」共同宣言に伴う
      コンビニエンスストア合同防犯訓練実施について
    - [2026-05-20] コンビニエンスストア統計調査4月度
  - date / title / URL 抽出 OK
  - 主要 7 testsuite regression: 145/145 pass
- **想定効果**:
  - Web-Repo 枠に JFA プレスリリース（月次コンビニ・FC 統計・ガイドライン
    改訂・業界公式発表）が中身付きで流入可能に
  - 7/8 朝刊で発覚した scraper 未実装状態が解消
- **設計特徴**:
  - HTTP 1 回で完結（一覧ページのみ、個別記事は叩かない）→ rate limit
    完全に非問題、JFTC (最大 21 HTTP) / Fitness Business (最大 11 HTTP)
    より更にシンプル
- **状態**: 完了
- **関連 commit**: C127

### 公正取引委員会 報道発表の scraper 未実装 → 完了

- **発見日**: 2026-06-19（朝刊レビュー、6/25 / 7/2 再発）
- **観察当初**: 2 面ウェブリポ記事として公取委ニュースを pick したが、
  scraper 未実装で「[scraper not implemented] 公正取引委員会 報道発表」
  表示。RSS unavailable、HtmlScrapeDriver subclass 未追加。7/2 には
  こころみ・ウェブリポ 2 社関連で登場し、中身なし
- **C120 実装**（2026-07-04, Sprint 11 第 1 案件）:
  - 公取委サイト構造調査:
    - robots.txt: 全 Allow、AI 向け `llms.txt` も提供
    - 個別記事 URL パターン: `/houdou/pressrelease/YYYY/{mon}/YYMMDD_xxx.html`
    - `<h1>(令和X年M月D日)実タイトル</h1>` 構造で date + title を分離抽出可
    - 本文は `<div class="p_title">` 以降、`<h2>関連ファイル</h2>` の前まで
  - `scripts/lib/drivers/jftc.py` 新規実装:
    - `JftcDriver(HtmlScrapeDriver)` サブクラス、`HOST = "www.jftc.go.jp"`
    - 当月 + 前月の月別 index を fetch（月替わり取りこぼし防止）
    - `parse_index_links()` で記事リンク抽出、`parse_article_page()` で
      title / date / body を分離
    - 令和 X 年 = 2018 + X 年で西暦変換
    - QueShinchoDriver（sitemap + JSON-LD、複雑）に比べて大幅にシンプル
  - `scripts/fetch.py` dispatch loop に JFTC 分岐追加（QUE と同パターン）
  - `tests/test_jftc.py` 新規（15 tests: 令和変換 / index parse /
    article parse / 定数 sanity）
- **動作確認**:
  - fetch CLI dry-run: 3 記事取得成功
    - ブロードコム・インコーポレイテッドに対する独占禁止法違反被疑事件の処理について
    - 北星学園大学における「独占禁止法教室」の開催について
    - 駒澤大学における「独占禁止法教室」の開催について
  - title (`(令和...)` prefix 剥がれ) / date (2026-07-03) / body 抽出 OK
  - 「125 sources」→「126 sources」に組み込み確認
- **想定効果**:
  - こころみグループ・ウェブリポ関連の公取委発表が中身付きで採用可能に
  - 独占禁止法違反、下請法違反、勧告等の企業ニュースが 2 面 / 3 面で流入
- **状態**: 完了
- **関連 commit**: C120

### 6 面ハイク欄コメントの UL バイアス → 完了

- **発見日**: 2026-06-25（朝刊レビュー）
- **観察**: 6 面 outdoor / hike コメント生成で、記事が UL でなくても
  「UL で軽量化を追いながら」等の UL 文脈を挿入するバイアス
  - 具体例：6/25 Atlas Obscura「フィンランドの煙サウナ」→ コメントで
    UL 装備の話に強引に接続
- **C117 実装**（2026-07-01）:
  - 発生源特定: `scripts/page6/prompts.py` の 3 箇所
    - `OUTDOOR_EVAL_GUIDE`: UL が単独筆頭に配置
    - `INTEREST_SUMMARY["outdoor"]` = "UL ハイキング・関東圏低山・
      ロングトレイル" のみ
    - `COLUMN_PROMPT_TEMPLATE`: 「記事の核を伝えつつ、神山氏の関心領域と
      接続する」が接続を強制
  - 修正: 3 箇所とも多様化
    - `OUTDOOR_EVAL_GUIDE`: UL を「ハイキング（UL / クラシック /
      ファミリー）」の 1 つに並列化 + 「自然観察・自然文化（サウナのような
      自然と身体の関係）」「キャンプ・アウトドアクッキング」を追加
    - `INTEREST_SUMMARY["outdoor"]`: 「アウトドア全般（UL / クラシック
      ハイキング、関東圏低山、ロングトレイル、自然観察・自然文化、キャンプ）」
    - `COLUMN_PROMPT_TEMPLATE`: 「**まず記事の主題に忠実に**書く。関心領域
      は記事の主題と自然に接続できる場合のみ言及、無理な接続をしない」を明示
  - 神山さんの UL 趣味は news_profile.md §4.7 の通り保持、prompt では
    「1 つの関心」として並列化
- **既存「6 面 ハイク欄 UL 偏り（記事側）」との関係**: 本 C117 で
  `OUTDOOR_EVAL_GUIDE` から UL 偏重を緩めたことで、Stage 2 記事選定時にも
  非 UL 記事が採用されやすくなる副次効果あり（記事側偏りも部分緩和）
- **7/2 朝紙面での効果確認予定**（神山さんレビュー）:
  - UL でない記事のコメントが自然か
  - UL 記事では引き続き自然に UL 言及されるか
- **状態**: 完了
- **関連 commit**: C117

### Psyche.co を記事プールに追加 → 完了

- **発見日**: 2026-06-28（月次選定セッション中）
- **背景**: Psyche.co は Aeon の姉妹メディア（心理学・哲学・神経科学・
  実存的問い）。Tribune 射程と高親和、W5/W7/W8/W9 の Aeon 4 週連続
  採用の偏重バランス調整 + W9「内受容感覚」（7/19-25）期間の自然な
  採用候補として追加検討していた
- **C116 実装**（2026-07-01）:
  - RSS URL: `https://psyche.co/feed.rss`（Aeon と同一パターン、既存
    Aeon RSS driver そのまま流用）
  - `sources/academic.md` に「6b. Psyche ✅」として追加（Aeon (#6) の
    姉妹関係を可視化する枝番）
  - fetch CLI dry-run: 3 記事取得成功（「Pierre Bourdieu: habitus」
    「The thinking style that makes people vulnerable to extremism」等、
    Tribune 射程との親和性が実物で確認）
  - 「125 sources」に組み込み確認
- **想定採用機会**:
  - W9「内受容感覚」（7/19-25）期間：Psyche の心理学・neuroscience
    エッセイが自然な候補
  - W5/W7/W8 の Aeon 連続採用の代替として、以降の Aeon vs Psyche
    バランス観察
- **状態**: 完了
- **関連 commit**: C116

### C128 疎通調査 → C129 sources.md parser regex 修正で完結

- **発見日**: 2026-07-09
- **観察当初**: C128 の Sprint 11 追加ソース疎通調査で「Psyche / BE-PAL /
  LitHub は Stage 2 に 8-9 件/日 到達するが final_score = None のまま
  (Stage 3 integrate_scores 未接続)」と報告
- **C129 Step 1 真因究明**:
  - 実コードを網羅 trace した結果、3 ソースとも fetch → Stage 1 → area/
    humanities filter → Stage 2 uncached → `integrate_scores()` を経由する
    経路が確立されており、**final_score は numeric 値が正しく付与される**
  - C128 の「final_score = None」は具体的 artifact に基づかない推測だった
    と判明（scores_2026-07-\*.json / stage2_shadow_2026-07-\*.json どちらも
    logs/ に存在しない）
  - archive で 3 ソースが選定されない現象は **layer 2 haiku prefilter で
    美意識 5/6 が 0 固定 → layer 3 の Marginalian / 3 Quarks Daily / Paris
    Review 等に final_score でスコア敗北している** 可能性が高い（ただし
    CleverHiker (layer 2) が 7/9 outdoor 勝利しており「layer 2 = 自動敗北」
    ではない）
- **C129 Step 1 副次発見: parser regex 2 bug**（本 C129 で修正）:
  - `_NUMBERED_PREFIX_RE = r"^(\d+)\.\s+(.+?)\s*$"` が `6b.` (letter suffix)
    にマッチせず、Psyche が prefix 込み `'6b. Psyche ✅'` として registered
  - `_STATUS_EMOJI_RE = r"\s+(✅|⚠️|⚠|❌|🔗)\s*$"` が `\s+` 必須のため
    「）✅」直後（全角括弧直後）の emoji を strip できず、LitHub は
    `'Literary Hub（LitHub）✅'`、BE-PAL は `'BE-PAL（ビーパル）✅'` として
    registered。副作用として全 3 ソースが `Status.PARTIAL` に fallback
    （本来 VERIFIED）
- **C129 実装**（2026-07-09）:
  - `scripts/lib/source.py`
    - `_NUMBERED_PREFIX_RE` → `r"^(\d+[a-z]*)\.\s+(.+?)\s*$"` (letter suffix
      accept)
    - `_STATUS_EMOJI_RE` → `r"\s*(✅|⚠️|⚠|❌|🔗)\s*$"` (leading whitespace
      optional)
  - **regression 確認**: 全 131 sources の name/status を before/after
    snapshot 比較、差分は上記 3 ソースのみ。他 128 sources は完全一致
  - 主要 testsuite pass: `test_source_language` 13/13、`test_source_allowlist`
    8/8、`test_source_layers` 23/23、`test_stage2_layered` 26/26、
    `test_stage2_shadow` 56/56、`test_todays_headlines` 39/39
    （`test_article_rotator` b2 は pre-existing fail、本修正と無関係）
- **修正後の状態**:
  - Registry 名がクリーン: `Psyche` / `Literary Hub（LitHub）` /
    `BE-PAL（ビーパル）`
  - Status: 全 VERIFIED
  - `classify_layer` は layer 2 のまま（LAYER_3_SOURCES 昇格判断は本 C129
    のスコープ外）
- **Sprint 12 積み残し（layer 2 評価設計の再検討）**:
  - 現行 Phase B 設計では layer 2 rest（top N% + K threshold 未満）が
    Haiku prefilter のみで採用され、美意識 5/6 が **強制 0**。これにより
    layer 3 の Sonnet full 評価ソースと同一枠競合すると構造的スコア不利
  - Sprint 11 追加ソース 3 件は現在すべて layer 2 だが、選定に到達しない
    のが「品質差」なのか「layer 2 の scoring 設計」なのか切り分けが必要
  - Sprint 12 で以下を検討:
    - LAYER_3_SOURCES 絞り込み（現行 37 件、Foreign Policy 等の未採用低頻
      度ソース含む）
    - layer 2 の美意識 5/6 補正設計（0 固定 → 3 デフォルトなど）
    - Sprint 11 追加 3 件のうち Psyche / LitHub は Aeon / Paris Review と
      同格の位置付けなので LAYER_3 昇格が妥当か検討
- **状態**: 完了（parser 修正のみ、layer 設計は Sprint 12 積み残し）
- **関連 commit**: C129

### C128 疎通調査 続 → C130 Web-Repo 系ソースの断続的 fetch 失敗調査 → 3 真因に切り分け完了

- **発見日**: 2026-07-09
- **観察当初**: C128 疎通調査で「Web-Repo 系 4 件 + JFA が断続的にしか
  fetch されない」と報告（7/5-7 評価到達 8 件、7/4/8/9 ゼロ、等の日次
  ばらつき）
- **C130 実データ収集**（GHA `audit-logs-2026-07-{04..09}` artifact 復元）:

  | Archive | JFTC | リユース | 食品新聞 | Fitness | JFA | Web-Repo stage |
  |---|---|---|---|---|---|---|
  | 7/4 | 1★ | 0 | 0 | 0 | 1★ | medium |
  | **7/5** | 0 | **0** | **0** | **0** | 0 | **high** |
  | 7/6 | 0 | 8 | 8 | 8 | 1★ | none |
  | 7/7 | 0 | 8 | 8 | 8 | 1★ | none |
  | 7/8 | 0 | 8 | 8 | 8 | 1★ | medium |
  | **7/9** | 0 | **0** | **0** | **0** | 0 | **high** |

  ★ = HtmlScrapeDriver placeholder（source.url 1 件、[scraper not implemented] title、実記事なし）

- **C130 真因** — 「断続的」の実態は 3 つの独立した原因に切り分け:

  **真因 ①【設計仕様】Page 2 Medium fetch は High 敗北時のみ発火**
  - `scripts/selector/page2.py:970-1032` の段階的選定: Stage 1 (high 共有
    pool) で `page2_final_score >= threshold(35.0)` の pick が出ると
    `stage_used="high"` で確定、その company の Stage 2 (medium fetch) は
    **未発火** で skip
  - Web-Repo High Priority「ビジネスチャンス」が 7/5 (41.07) / 7/9 (46.75)
    で threshold 通過 → その日 Medium (リユース / 食品新聞 / Fitness
    Business / JFA) は fetch されず 0 entries
  - **「断続的」の 8 割はこの by-design な stage 制御**。修正の要否は
    「Medium も毎日確実に fetch したい」という意向次第（下記 B 参照）

  **真因 ②【本物のバグ】JFTC Akamai WAF が GHA runner IP を 403 ブロック**
  - GHA run 実測: `[jftc] fetch fail https://www.jftc.go.jp/houdou/pressrelease/2026/{jun,jul}/index.html: HTTP Error 403: Forbidden`（server: AkamaiGHost）
  - Local WSL からは同じ `DEFAULT_ARTICLE_UA` で 200 OK 確認、robots.txt も
    `User-agent: * Allow: /` で許可的
  - 結論: **UA 起因ではなく Akamai edge の IP-based bot detection**。
    GHA hosted runner の IP 範囲が blocked
  - 副作用: 公取委が page2 High pool に常に流入せず、ビジネスチャンス
    独占を構造的に強化

  **真因 ③【時間経過で自然解決】JFA C127 実装が cron 7/8 UTC より後**
  - C127 (b1b93db) commit 2026-07-09 04:01 UTC
  - Archive 7/9 の cron: 2026-07-08 18:54 UTC （C127 前）
  - 全 archive 7/4-7/9 で HtmlScrapeDriver placeholder が動作、
    source.url 1 entry のみ（scores 上は 1 だが実記事なし）
  - Archive 7/10 (今夜 7/9 UTC cron) 以降で C127 本格発火予定

- **C130 修正実施 → 別 commit で JftcDriver 個別 UA override**:
  - JftcDriver 内でのみ Akamai bot detection を回避する UA を使用
  - 全体 `DEFAULT_ARTICLE_UA` は変更しない（影響範囲を JFTC に限定）
  - 修正後、cron 7/9 UTC 以降で `[jftc] fetch fail` の 403 が解消される
    ことを観察

- **C（JFA C127 反映）**: 7/10-11 の archive を観察、自然発火確認予定

- **B（Web-Repo Medium 毎日 fetch）観察後判断保留**:
  - C130 真因 ② の JFTC UA 修正が入ると、公取委が page2 High pool に
    入り Web-Repo High の競争構造が変わる（ビジネスチャンス独占が
    緩む）→ Medium 発火頻度も自然に増える可能性
  - A 修正後 2-3 日観察してから B 着手判断
  - 判断材料: 修正後 3 日間の Web-Repo stage_used 分布、公取委が
    High で pick される日の割合、Medium 発火頻度の変化

- **状態**: 調査完了、A 実施済、B/C 観察待ち
- **関連 commit**: C130 (調査記録 + JftcDriver UA override)

### C132 layer3 昇格 + C133 降格第1弾 + dead weight 整理 → 完了

- **発見日**: 2026-07-09
- **背景**: Phase B 再設計の第一歩。神山さん Phase B コスト目標 $30-50/月
  に対する現状 $96/月 の圧縮のため、C132 で採用実績集計 → C133 で判断
- **C132 Step 1（Psyche + LitHub 昇格、commit `f266169`）**:
  - Psyche（Aeon 姉妹サイト、C116 追加、academic:国際）→ layer 3
  - Literary Hub（LitHub）（C125 追加、books:海外純文学）→ layer 3
  - W9「内受容感覚」（7/19-25）期間の Psyche 記事を Sonnet フル評価で
    捕捉する目的
- **C132 Step 2 集計結果（30 日 2026-06-10 〜 2026-07-09）**:
  - LAYER 3 全体の月次 Sonnet コスト: $68.45/月（採用ゼロ 13 ソース =
    $22.59/月 = 33% が waste）
  - Sonnet per-entry cost 実測: $0.01115（llm_usage_*.json 集計から算出）
  - 詳細テーブルは C132 report 参照
- **C133 Step 1 降格 11 件**（採用ゼロ × 高コスト、想定削減 約 $21/月）:
  - Foresight（新潮社）※新潮QUE 統合で 2026-05-17 以降新記事なし、
    sources/geopolitics.md に「休刊済」明記
  - Stanford Encyclopedia of Philosophy（SEP）
  - 集英社新書プラス / Foreign Affairs（CFR）/ Philosophy Now
  - Quanta Magazine / 春秋社 / CSIS / London Review of Books（LRB）
  - 青土社（現代思想）/ DIAMONDハーバード・ビジネス・レビュー（DHBR）
  - 降格後も layer 2（Haiku prefilter 経路）で評価継続、完全遮断ではない
- **C133 Step 2 dead weight 11 件を LAYER_3 定義から除外**（コスト影響
  ゼロ、定義の健全化）:
  - NBR / 日本認知科学会 / PhilPapers / RAND / HBR.org / Brookings /
    Aeon（Psychology / Philosophy）/ NBER / WEBちくま / Behavioral Scientist /
    東大 GraSPP
  - eval 0 のまま LAYER_3 に居るのは「LAYER_3 定義が形骸化」の状態
    （fetch 失敗 or 記事流入なし）
- **C133 維持 17 件**（採用実績 15 + 新規 2）:
  - 地政学: Project Syndicate / Foreign Policy / War on the Rocks
  - 学術人文: Aeon / **Psyche**(C132) / 3 Quarks Daily / Public Books /
    The Point Magazine / n+1
  - 経営思想: MIT Sloan Management Review / McKinsey Insights
  - 思想・科学哲学 + 文学: NYRB / The Paris Review /
    **Literary Hub（LitHub）**(C132) / The Marginalian / AXIS / Nautilus
- **降格後の LAYER_3_SOURCES 件数**: 39 → **17**（動的 QUE 1 件を含めて 18）
- **実測計画**（3-5 日）:
  - 次の cron 7/9 UTC (JST 7/10 早朝) から降格反映
  - 3-5 日実測で $75 想定との突合（$96 現状 - $21 削減想定）
  - 目標 $50 への残ギャップ ≈ $25 → 第 2 弾降格の候補は eval 実測後判断
- **状態**: 完了
- **関連 commit**: C132 (`f266169`) / C133 (本 commit)

### C133 副次課題 — LAYER_3 定義除外 11 件の fetch 復旧（Sprint 12+ 別案件）

- **発見日**: 2026-07-09（C132 30 日集計で eval 0 として発覚）
- **観察**: 以下 11 ソースは LAYER_3_SOURCES に居ながら 30 日間 Stage 2
  評価に 1 件も到達していない = fetch 経路が壊れているか記事流入自体が
  ない状態:

  | ソース | 想定原因 | 修復難易度 |
  |---|---|---|
  | NBR（National Bureau of Asian Research） | RSS 未検証 or 未実装 | 中 |
  | 日本認知科学会 | status=FAILED、fetch_method=BLOCKED | 高（RSS 廃止？） |
  | PhilPapers | status=FAILED、fetch_method=BLOCKED | 高 |
  | RAND Corporation | RSS 未検証 or 実装ミス | 中 |
  | Harvard Business Review（HBR.org） | Cloudflare / rate limit 予想 | 中〜高 |
  | Brookings Institution | RSS parse error 観測 | 中 |
  | Aeon（Psychology / Philosophy） | companies.md name collision の dead entry | 低（削除で OK） |
  | NBER Working Papers | RSS 未検証 or 未実装 | 中 |
  | WEBちくま | status=FAILED、fetch_method=BLOCKED | 高（RSS 廃止？） |
  | Behavioral Scientist | RSS 未検証 or 未実装 | 中 |
  | 東京大学 公共政策大学院（GraSPP） | RSS 未検証 or 未実装 | 中 |

- **判断**: C133 では LAYER_3 定義から除外のみ実施。fetch 復旧は別案件
  として Sprint 12/13 で個別調査。復旧できたら都度 LAYER_3 復帰判断
- **優先順**: 低（現在の紙面編集への直接影響なし、コスト影響もゼロ）
- **状態**: 未着手（Sprint 12/13 backlog）
- **関連 commit**: C133 で LAYER_3 から除外のみ

### C134 stage2 同一記事再評価調査 → C135 cross-day score cache 実装 → 完了

- **発見日**: 2026-07-09
- **背景**: C132 集計時に「layer3 主要ソースが 30 日で ~310 件 = 1 日 10-11 件」
  という cadence が偶然 fetch top_n と一致することに違和感、C134 調査へ
- **C134 実測発見**（直近 7 日 audit-logs から）:
  - Stage 2 総評価件数: 3,103 件、うちユニーク URL 1,541 件、**再評価 1,562 件 (50.3%)**
  - 毎日評価される URL: 109 件 (7.1%)、その 763 evals が総評価の 24.6%
  - 再評価コスト: **月次 $47.25**（うち Sonnet $42.64、Haiku $4.63）
  - 発生機構: 各 caller が `no_dedupe=True` で毎日 RSS 最新 N 件を fetch →
    Stage 2 が URL キャッシュを一切参照せず LLM 呼出 → `write_scores_log` は
    当日 log のみ更新、昨日以前は読まれない
- **C135 実装** (`scripts/selector/stage2.py`):
  - `_load_recent_scores(lookback_days=7, exclude_today=True, log_dir=...)`:
    過去 N 日の `logs/scores_YYYY-MM-DD.json` を URL→entry 辞書化。
    newer overwrites older（last-write-wins）
  - `_is_cache_hit(cached_entry, expected_sonnet_model)`: **保守的ルール**で
    Sonnet 完全評価 (`sonnet_full` / `legacy_sonnet` / pre-C85 legacy None)
    のみ再利用。Haiku 評価は再利用しない（安価 $0.0016 + 美意識 5/6=0 の
    staleness 回避）
  - `_apply_cache_hits(articles, cache, ..., caller)`: articles を
    (uncached, hits) に分割。hit エントリは `cache_hit=True` /
    `cache_source_date` / `cache_original_caller` を添付、caller を現行に再割当、
    `final_score` は None にリセット（Stage 3 で再計算）
  - `run_stage2()` 冒頭で cache lookup → uncached だけ legacy/layered 経路に
    渡す → cache hits をマージ → `write_scores_log` を **top-level で 1 回**
    呼ぶ（`_run_stage2_layered` / 新設 `_run_stage2_legacy` 内部の
    `write_scores_log` は削除、errors 二重登録を防ぐ）
  - `Stage2Result.cache_hits_count` フィールド追加（観察用）
- **revert 手段**:
  1. **env var**: GHA workflow に `TRIBUNE_STAGE2_CACHE_DAYS: '0'` を追加
     → 次の cron から cache 経路無効化、従来通り全件 LLM 評価
  2. **defaults**: `DEFAULT_CACHE_LOOKBACK_DAYS = 0` に変更 + commit
  3. **git revert**: 本 commit を revert して 1 行変更で完全に旧挙動
- **テスト** (28 件全 pass、`tests/test_stage2_cache.py` 新設):
  - (a) env var: 未設定 / 0 / 正の値 / 負値 / 不正文字列 の各パス
  - (b) load: lookback=0 / 不在 dir / 3 日分読み込み / today 除外 /
    newer overwrites / malformed JSON skip
  - (c) hit判定: sonnet_full / legacy_sonnet / pre-C85 None (全 hit) /
    haiku_full / haiku_prefilter_only (全 miss) / model mismatch / model 欠落 /
    スコア全 None
  - (d) split: 空 cache / hit+miss+haiku 分割 / メタデータ / URL 欠落 article
  - (e) integration: `cache_lookback_days=0` / env=0 / `write_scores_log`
    top-level 1 回のみ (legacy + layered) / hit=1 miss=1 で LLM 1 回のみ
  - 主要 20 testsuite (test_stage2_layered / shadow / source_layers / QUE 等)
    regression 0 件
- **副次修正**: C133 の sources/geopolitics.md で Foresight heading 末尾に
  `**休刊済**` を追加していたが `_STATUS_EMOJI_RE` が末尾 emoji を strip
  できず、name に markdown が残って `test_source_language e2` を破損させて
  いた（C133 で気づかず push、C135 で発覚）。heading から `**休刊済**` を
  削除、休刊メモは position 位置付け body に既存記述あり
- **想定効果**:
  - Sonnet 再評価コスト $42.64/月 の大部分を削減
  - 現実値（cache miss / model 変動考慮）: **$30-38/月削減**
  - C133 の $21/月 と合算で **$51-59/月削減 → 現状 $96 → $37-45/月**
  - Phase B 目標 **$30-50/月 到達可能性大**
- **観察 checklist**（3-5 日 = 2026-07-12 頃）:
  - GHA run log の `[stage2.cache:{caller}] lookback=7d total=... hits=... miss=... hit_ratio=...%`
    行を集計、caller 別 hit_ratio が 30-50% 前後になっているか
  - `audit-logs-*` の scores log で `cache_hit=True` エントリの割合
  - `llm_usage_*.json` で `stage2.batch.layer3.sonnet.*` の月次相当コストが
    $75 (C133 想定) → $37-45 (C135 想定) に落ちているか
  - **紙面品質**: 神山さんレビューで cached score による選定に違和感がないか。
    特に W9「内受容感覚」（7/19-25）期間の Psyche/LitHub 昇格影響と混同しないよう、
    C133 昇格分と cache hit の telemetry を分けて追う
- **状態**: 実装完了、観察待ち
- **関連 commit**: C135 (本 commit)

### 2 面 Headlines 英語ソース（BBC 等）の和訳消失 → 仕様として受容

- **発見日**: 2026-06-29（W6 Day 2 朝刊レビュー）
- **観察当初**: 以前は BBC 等英語ソースが日本語訳で表示されていたが、
  6/29 朝刊では英語のまま表示。神山さん「これって仕様だっけ？」
- **C109 真因究明**（2026-06-30）:
  - 「翻訳機能の回帰」ではなく **「BBC の Page I 採用 → Today's Headlines
    降格」** が真因
  - Page I 採用時: `article-title-japanese` でフル翻訳（5/10 例：
    「デビッド・アッテンボロー卿はどのようにして…」）
  - Today's Headlines 採用時: `_render_todays_headlines` は description
    truncate のみ、翻訳経路なし（6/28 例：「Lithium battery fires...」）
  - Sprint 9 改革（C42 / C75 / C76 / C79）によるソース多様化の自然な結果
- **神山さん判断**: 選択肢 C（仕様として受容、様子見）
- **将来検討（Sprint 11+）**: Today's Headlines にタイトル翻訳経路を追加する
  なら別案件として扱う
- **状態**: 完了（仕様として受容）
- **関連 commit**: C109 調査結果報告のみ

### Sprint 9 中の主要観察事項

下記は Sprint 9 期間（2026-05 後半 〜 2026-06 上旬）中に着手・完了した
主要観察項目。詳細は各 C 番号で `git log --grep=C<n>` または
コミットメッセージから参照可能。

- **C36**: （内容詳細追記欄）
- **C42**: （内容詳細追記欄）
- **C49**: （内容詳細追記欄）
- **C66**: （内容詳細追記欄）
- **C68**: （内容詳細追記欄）

---

## 参考リンク

- `docs/themes.md` — Tribune テーマプール（W5 まで運用）
- `data/monthly_pivotal.json` — 月次選定主軸記事（W1〜W5）
- `CLAUDE.md` — プロジェクト指示書
- `design_spec.md` — 朝刊設計仕様書
- `news_profile.md` — 読者プロファイル

---

**文書バージョン**: v0.1（C91: 初版、2026-06-18）
**更新者**: 神山晃男 / Claude Code
