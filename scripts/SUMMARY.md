# scripts/ — モジュールサマリ

`scripts/` 配下のPythonモジュール一覧。Phase 1 の fetch infrastructure（10モジュール、約1300行）を3分で把握できるよう整理。

---

## 依存関係マップ

```
[CLI エントリポイント]

scripts.fetch                    ──┬──→ lib/source.py
  (sources/*.md ベースの汎用CLI)    ├──→ lib/config_loader.py
                                   ├──→ lib/drivers/rss.py
                                   ├──→ lib/drivers/html.py
                                   └──→ lib/dedupe.py

scripts.regen_front_page         ──┬──→ lib/source.py
  (Page I ライブ更新パイプライン)    ├──→ lib/config_loader.py
                                   ├──→ lib/drivers/rss.py
                                   ├──→ lib/drivers/html.py (BbcArticleScraper)
                                   ├──→ scripts/translate.py
                                   └──→ scripts/render.py

[内部依存]

lib/drivers/rss.py    ──→ lib/drivers/base.py + lib/source.py
lib/drivers/html.py   ──→ lib/drivers/base.py + lib/source.py
lib/dedupe.py         ──→ lib/source.py (Article)
lib/config_loader.py  ──→ lib/drivers/base.py (SiteConfig)
lib/llm.py            ──→ (Phase 2 で anthropic SDK を import 予定)
lib/llm_usage.py      ──→ stdlib のみ（Phase 2 LLM呼び出しから利用）
```

**実行コマンド**：
- `python3 -m scripts.fetch [--category ... --priority ... --source ... --limit N --no-dedupe]`
- `python3 -m scripts.regen_front_page`

---

## 1. scripts/fetch.py

**目的**：`sources/*.md` の全ソースから RSS / HTML 経由で記事を取得する汎用CLI。

**主要関数**
- `select_sources()`：カテゴリ／優先度／名前substring／ HTML含むかでフィルタ
- `run()`：プログラマティックな entry（テスト・他スクリプトから呼び出し可）
- `_print_summary()`：取得件数・per-source 内訳・失敗一覧を stderr に出力
- `main()`：argparse でCLI引数解析

**外部依存**：標準ライブラリのみ（urllib、xml.etree、tomllib、json）

**失敗モード**
- 個別ソース fetch 失敗：例外を捕捉して `failures` に記録、他ソース続行
- 全ソース 0件：戻り値1（`--no-dedupe` 時は0）

**読み書きするファイル**
- 読込：`sources/*.md`（全ファイル）、`config/site_overrides.toml`、`logs/urls_*.json`
- 書込：`logs/urls_<today>.json`（dedupe ログ）

---

## 2. scripts/regen_front_page.py

**目的**：BBC Business RSS の最新記事で Page I を書き換える本番パイプライン（旧 `experiment/regen_front_page.py` のリファクタ版）。

**主要関数**
- `_bbc_source()`：BBC feed 取得用の合成 Source オブジェクトを構築
- `filter_explainers()`：解説型タイトル（"How"/"What"/"Why"）をスキップ
- `promote()`：タイトルに "AI" を含む記事をTOPに昇格
- `enrich_with_body()`：BBC記事ページから本文段落取得＋翻訳
- `main()`：fetch → filter → promote → translate → render → replace の通し実行

**外部依存**：BBC RSS、BBC記事HTML、Google Translate gtx、MyMemory（フォールバック）

**失敗モード**
- BBC feed 取得失敗：戻り値1で異常終了
- 解説スキップ後の残存件数 < 4：戻り値1
- 本文段落抽出 0件：description で fallback（rendering 自体は続行）
- 翻訳失敗：原文をそのまま表示

**読み書きするファイル**
- 読込：BBC RSS、BBC個別記事ページ、`archive/2026-04-25.html`
- 書込：`archive/2026-04-25.html`（Page I のみ surgical replace）

---

## 3. scripts/translate.py

**目的**：英→日翻訳のフォールバック付きラッパー。

**主要関数**
- `translate_google()`：Google Translate gtx エンドポイント（非公式、無料）
- `translate_mymemory()`：MyMemory API（フォールバック、無料枠50,000字/日）
- `translate()`：Google → 失敗時 MyMemory に自動切替
- `translate_meta()`：記事dictの `title_ja` / `desc_ja` を一括populate

**外部依存**：translate.googleapis.com（gtx 非公式）、api.mymemory.translated.net

**失敗モード**
- Google API 失敗：MyMemory フォールバック発動（stderr に warn）
- 両方失敗：`None` を返す。呼び出し側は原文を使う想定
- gtx 非公式エンドポイント：仕様変更リスクあり（roadmap.md §4.2 既知の脆さ）

**読み書きするファイル**：なし（純粋関数）

---

## 4. scripts/render.py

**目的**：Page I の HTML 構築と既存ファイルへの surgical 置換。

**主要関数**
- `render_top_body()`：TOP記事の本文（dropcap + 段落）構築
- `render_secondary_body()`：セカンド記事3本の本文構築
- `build_page_one()`：第1面全体（lead-story + sidebar + secondaries）
- `replace_page_one()`：`<section class="page page-one">…</section>` を文字列検索で1箇所だけ置換

**外部依存**：標準ライブラリのみ（html escape）

**失敗モード**
- page-one section が0または2以上：`RuntimeError`（surgical置換が安全に行えない）
- `</section>` 終端が見つからない：`RuntimeError`

**読み書きするファイル**：なし（純粋関数。呼び出し側がファイルI/Oを担当）

---

## 5. scripts/lib/source.py

**目的**：Source / Article のドメインモデル＋ `sources/*.md` からSource records を抽出するMarkdownパーサ。

**主要関数**
- `Source` / `Article` dataclass：fetch_method（rss/html/blocked）・priority・status を含む
- `parse_sources_md(path)`：1ファイルパース、companies.md の3階層構造と他ファイルの2階層構造を両対応
- `load_all_sources(dir)`：`sources/*.md` 全ファイルを再帰パース
- `_extract_status()`：見出しの末尾emoji（✅/⚠️/❌、variation selector対応）から status 判定
- `_decide_fetch_method()`：RSS フィールドのテキストから fetch_method（rss/html/blocked）を決定

**外部依存**：標準ライブラリのみ（re、dataclasses、pathlib）

**失敗モード**
- ファイルが存在しない：呼び出し側で例外
- パース失敗（不正な見出し等）：該当ブロックを silently skip（他は続行）
- URLが取れないソース：fetch_method = HTML 落ち（HtmlScrapeDriver でスタブ化）

**読み書きするファイル**：読込 `sources/*.md` 全ファイル

---

## 6. scripts/lib/config_loader.py

**目的**：`config/site_overrides.toml` を SiteConfig オブジェクトに変換。

**主要関数**
- `load_site_config(path=None)`：TOML を読み込み、`[sites.<host>]` テーブルを SiteConfig.overrides に展開

**外部依存**：標準ライブラリのみ（tomllib、Python 3.11+ 必須）

**失敗モード**
- TOMLファイル不在：空のSiteConfig を返す（全ソースがデフォルトUA）
- TOMLパース失敗：`tomllib.TOMLDecodeError` を呼び出し側に伝搬

**読み書きするファイル**：読込 `config/site_overrides.toml`

---

## 7. scripts/lib/dedupe.py

**目的**：直近7日のURL履歴で重複記事を除外（`logs/urls_YYYY-MM-DD.json`）。

**主要関数**
- `load_recent_urls(today)`：直近 RETENTION_DAYS（7日）のログファイルからURL集合を構築
- `append_today(articles, today)`：今日のログファイルに追記（同日内多重実行も merge）
- `dedupe(articles, today)`：直近URLに含まれる記事を filter

**外部依存**：標準ライブラリのみ（json、datetime、pathlib）

**失敗モード**
- ログファイル破損（不正JSON）：silently skip、他の日のログは続行使用
- ログディレクトリ不在：`mkdir(parents=True, exist_ok=True)` で自動作成

**読み書きするファイル**：読込・書込 `logs/urls_YYYY-MM-DD.json`

---

## 8. scripts/lib/drivers/base.py

**目的**：SourceDriver 抽象基底クラス＋ SiteConfig（per-host UA/notes）。

**主要要素**
- `SourceDriver` ABC：`fetch(source) -> Iterable[Article]` を強制
- `SiteConfig`：URL → host 抽出 → host別 overrides を引く
  - `user_agent_for(url)`：UA上書き（デフォルト `kt-tribune/0.6 (+local)`）
  - `note_for(url)`：人間向けメモ取得
- `DEFAULT_USER_AGENT` / `DEFAULT_TIMEOUT` 定数

**外部依存**：標準ライブラリのみ（abc、dataclasses、urllib.parse）

**失敗モード**：N/A（純粋データ構造）

**読み書きするファイル**：なし

---

## 9. scripts/lib/drivers/rss.py

**目的**：RSS 1.0 (RDF) / RSS 2.0 / Atom 1.0 の3 dialect を統一インターフェースで扱う。

**主要関数**
- `RssDriver.fetch(source)`：URL を取得 → XML パース → Article のリスト
- `_iter_items(root, source)`：tree を namespace-blind に walk、local-name "item"（RSS/RDF）or "entry"（Atom）を Article に変換
- `_extract_link(item)`：RSS の text link と Atom の `href` 属性を統一
- `_parse_date(text)`：RFC-822（pubDate）と ISO-8601（updated/dc:date）の両対応

**外部依存**：標準ライブラリのみ（urllib、xml.etree、email.utils）

**失敗モード**
- HTTP 4xx/5xx・タイムアウト：stderr に `[rss] FAIL` を出力、空リストを返す
- XMLパース失敗：stderr に `[rss] PARSE` を出力、空リストを返す
- 日付パース失敗：`pub_date = None`（記事自体は採用）

**読み書きするファイル**：なし（外部HTTPのみ）

---

## 10. scripts/lib/llm.py（Phase 2 scaffold）

**目的**：Anthropic API キーの環境変数取り込み＋Phase 2 用エントリポイント `call_claude()` のスタブ。

**主要関数**
- `get_api_key()`：`ANTHROPIC_API_KEY` 環境変数を読み、`sk-ant-` 接頭辞を検証
- `call_claude(messages, model=DEFAULT_MODEL, **kwargs)`：Phase 2 で実装予定（現状 `NotImplementedError`、docstring に実装パターンを記述）

**外部依存**：標準ライブラリのみ（`os`）。Phase 2 着手時に `anthropic` SDK を追加予定

**失敗モード**
- 環境変数未設定：`RuntimeError`（actionable メッセージで `~/.bashrc` 設定法を案内）
- 不正な key 形式（`sk-ant-` で始まらない）：`RuntimeError`

**読み書きするファイル**：なし（環境変数のみ）

---

## 11. scripts/lib/llm_usage.py（Phase 2 scaffold）

**目的**：Anthropic API 呼び出しの日次トークン・コスト記録＋暴走防止のキャップ機構。Anthropic Console の月額予算（一次防御）を補う二次防御。

**主要関数**
- `estimate_cost(model, input_tokens, output_tokens)`：USD コスト推定（Sonnet 4.6 / Opus 4.7 / Haiku 4.5 の単価をハードコード）
- `check_caps(today)` → `CapStatus`：呼び出し前に確認、`ok=False` なら停止
- `record_call(model, input_tokens, output_tokens, today)`：呼び出し後に追記
- `daily_summary(today)`：今日の totals 取得

**キャップ値**：`DAILY_COST_CAP_USD = 0.50`（設計予測の5倍）、`DAILY_CALLS_CAP = 200`（設計予測の10倍）

**外部依存**：標準ライブラリのみ（`json`、`datetime`、`pathlib`）

**失敗モード**
- ログファイル破損（不正JSON）：silently 空ログから再開（pipeline 停止より優先）
- 未知モデル（`MODEL_PRICING` に未登録）：コスト 0 として記録（致命ではないが、新モデル採用時はテーブル更新必須）

**読み書きするファイル**：読込・書込 `logs/llm_usage_YYYY-MM-DD.json`

---

## 12. scripts/lib/drivers/html.py

**目的**：(a) HtmlScrapeDriver の placeholder スタブ、(b) BBC記事ページからの本文抽出。

**主要要素**
- `HtmlScrapeDriver.fetch()`：「scraper not implemented」プレースホルダ Article を1本返す（per-site サブクラスで上書き想定、Phase 2以降で山と道Shopify／YAMAP SaaS 等用に実装）
- `BbcArticleScraper.paragraphs(url, max_n)`：BBCの styled-component class `sc-XXXX` を正規表現で抽出 → タグ除去 → 整形 → 60〜480文字の段落を最大N本

**外部依存**：BBC News 記事ページ（CSS 命名規則変更で破綻リスク、roadmap.md §4.2 既知の脆さ）

**失敗モード**
- HTTP 失敗：stderr に `[bbc-scrape] FAIL`、空リスト
- BBC が `sc-` prefix を変えた場合：silently 0件返却（テスト推奨：roadmap.md §4.4 技術的負債）

**読み書きするファイル**：なし（外部HTTPのみ）

---

## バージョン

- v1.0：2026-04-27 Phase 1 完了直後に作成
- 次回見直し：Phase 2 Sprint 1 完了時（選定ロジック追加で該当セクション拡張）
