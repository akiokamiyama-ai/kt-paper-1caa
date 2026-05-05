# Kamiyama Tribune — Setup Guide

毎朝 5:00 AM JST に自動生成・自動公開される朝刊のセットアップ手順。
PC は起動していなくて良い（GitHub Actions + Vercel の完全クラウド構成）。

---

## アーキテクチャ

```
JST 5:00 AM (= UTC 20:00)
  │
  ▼
GitHub Actions (.github/workflows/daily.yml)
  ├─ ubuntu-latest VM 起動
  ├─ Python 3.12 + pip install -r requirements.txt
  ├─ Secrets から API キー 3 本を環境変数に注入
  ├─ python -m scripts.regen_front_page_v2 --date <today JST>
  ├─ archive/YYYY-MM-DD.html 生成
  ├─ cp archive/YYYY-MM-DD.html index.html
  └─ git add archive/ index.html logs/ && git commit && git push
       │
       ▼
Vercel が main への push を検出
  └─ 静的ファイルをデプロイ（数十秒）
       │
       ▼
JST 5:05 AM 頃
  https://<your-vercel-domain>/ で当日朝刊が閲覧可能
```

---

## 1. GitHub Secrets の登録

GitHub Actions が API キーを参照するため、暗号化された secrets として登録する。

### 手順

1. リポジトリページを開く（`https://github.com/akiokamiyama-ai/kt-paper-1caa`）
2. **Settings** → 左メニュー **Secrets and variables** → **Actions**
3. **New repository secret** ボタン
4. 以下 3 つを順に登録：

| Name | Value |
|---|---|
| `ANTHROPIC_API_KEY` | `~/.bashrc` の `ANTHROPIC_API_KEY` の値 |
| `MIIBO_API_KEY` | `~/.bashrc` の `MIIBO_API_KEY` の値 |
| `MIIBO_AGENT_ID` | `~/.bashrc` の `MIIBO_AGENT_ID` の値 |

### 仕組み

- GitHub に保存された secrets は **AES-256 で暗号化**され、登録後は GitHub UI 上でも値を読めない（マスクされる）
- workflow 実行時のみ復号され、環境変数として VM に注入される
- VM 終了時に env は破棄される
- workflow log にも自動マスクされる（`ANTHROPIC_API_KEY: ***`）

---

## 2. GitHub Actions 動作確認

Secrets 登録後、まず手動で動作確認する：

1. リポジトリ → **Actions** タブ
2. 左サイドバー **Daily Tribune Generation** を選択
3. 右上 **Run workflow** ドロップダウン → **Run workflow** ボタン
4. 数秒後に runner が起動。所要時間は **約 20–25 分**（Stage 1〜6 + 編集後記の LLM 呼び出し合計）
5. 完了したら：
   - 緑チェック → `archive/<today>.html` と `index.html` が main に push されている
   - 赤バツ → ログを確認、API キー誤りや cap 超過などを判別

> **Note**: schedule 起動（5:00 JST）は 23:00 UTC など GitHub の混雑時間帯にズレる場合があり、5–15 分遅れることがある。これは GitHub の仕様。

---

## 3. Vercel セットアップ

### 手順

1. <https://vercel.com> にアクセス
2. **Sign Up** または **Log In** → **Continue with GitHub**
3. ダッシュボード → **Add New** → **Project**
4. Import Git Repository から `akiokamiyama-ai/kt-paper-1caa` を選択（private repo OK）
5. Configure Project：
   - **Framework Preset**: `Other`
   - **Root Directory**: `./`（デフォルト）
   - **Build Command**: 空欄（`vercel.json` で制御済み）
   - **Output Directory**: `./`
   - **Install Command**: 空欄
6. **Deploy** クリック
7. 30〜60 秒で初回デプロイ完了。`https://kt-paper-1caa.vercel.app` のような URL が発行される
8. Settings → **Domains** で URL を確認・必要ならカスタムドメイン設定

### 動作確認

- 発行された URL を開く → `index.html`（= 当日 archive のコピー）が表示される
- ブラウザの開発者ツール → Network → response headers に `X-Robots-Tag: noindex,nofollow` が付与されていることを確認
- `https://<domain>/robots.txt` が `User-agent: * / Disallow: /` を返すことを確認

### 自動デプロイの動作

- GitHub Actions が main に push → Vercel が webhook で検出 → Production deployment（30 秒程度）
- 設定不要。Vercel は GitHub App として自動連携している

---

## 4. ローカル開発環境

GitHub Actions に頼らずローカルで再生成したい場合：

```bash
# 環境変数（~/.bashrc に既に設定済みのはず）
export ANTHROPIC_API_KEY=sk-ant-...
export MIIBO_API_KEY=...
export MIIBO_AGENT_ID=...

# 依存
python3 -m pip install --user --break-system-packages -r requirements.txt

# 当日生成
python3 -m scripts.regen_front_page_v2 --date $(date +%Y-%m-%d)

# index.html に反映したい場合
cp archive/$(date +%Y-%m-%d).html index.html
```

または緊急時バックアップとしての wrapper：

```bash
/home/akiok/projects/tribune/scripts/cron/daily_run.sh
tail -40 /home/akiok/projects/tribune/logs/cron_$(date +%Y-%m-%d).log
```

---

## 5. 失敗時の確認方法

### GitHub Actions の log

リポジトリ → **Actions** → 該当 run をクリック → 失敗したステップを展開

よくある原因：

| 症状 | 原因 | 対処 |
|---|---|---|
| `Authentication failed` | Secrets 未登録 / 値の改行混入 | Secrets を再登録（前後空白に注意）|
| `DAILY_COST_CAP_USD exceeded` | LLM コスト超過 | python 側で正常 abort、archive は中断状態。翌日リトライ |
| `timeout-minutes: 30 exceeded` | Anthropic API レイテンシ悪化 | workflow を再実行 / timeout を伸ばす |
| commit step で push 失敗 | `permissions.contents: write` 欠落 | workflow yaml を確認 |

### Vercel が反映されない

- Vercel ダッシュボード → 該当 project → **Deployments** タブ
- main への push 後数十秒以内に新しい deployment が並ぶはず。並ばなければ GitHub 連携を再認証

---

## 6. 関連ファイル一覧

| パス | 役割 |
|---|---|
| `.github/workflows/daily.yml` | GitHub Actions の cron 定義 |
| `requirements.txt` | Python 依存 |
| `vercel.json` | Vercel 静的ホスティング設定 |
| `robots.txt` | クローラー全拒否 |
| `index.html` | エントリー（毎朝 archive/YYYY-MM-DD.html で上書き）|
| `archive/YYYY-MM-DD.html` | 各日の朝刊本体 |
| `logs/*.json` | 連日の dedup state / rotation history（git で永続化） |
| `scripts/cron/daily_run.sh` | 緊急時ローカル fallback |
| `scripts/regen_front_page_v2.py` | パイプライン本体 |
