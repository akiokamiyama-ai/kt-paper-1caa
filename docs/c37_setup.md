# C37 コメント入力 UI — 設定手順書

Sprint 9 第 1 弾。Tribune の編集後記下に「コメントを書く →」リンクを設置し、
Web フォームから `data/comments/YYYY-MM-DD.md` に GitHub commit する。

実装は完了済（commit 履歴参照）。本書は **デプロイ時の env var 設定手順**。
神山さんが Vercel Dashboard で 3 つの env var を設定するだけで稼働開始する。

---

## 1. 事前準備：Fine-grained PAT の発行（GitHub）

1. GitHub にログイン → 右上アバター → **Settings**
2. 左下メニュー → **Developer settings** → **Personal access tokens** → **Fine-grained tokens**
3. **Generate new token** をクリック

### トークン設定

| 項目 | 値 |
|---|---|
| Token name | `tribune-comment-ui` |
| Expiration | **365 days**（1 年。期限前にリマインダーで更新） |
| Resource owner | `akiokamiyama-ai` |
| Repository access | **Only select repositories** → `kt-paper-1caa` |

### Repository permissions

| Permission | Access |
|---|---|
| **Contents** | **Read and write** |
| その他 | すべて No access |

→ **Generate token** をクリック。表示された `github_pat_...` で始まる文字列を **その場でコピー**（一度しか表示されない）

---

## 2. パスワードを決める

任意の文字列で OK。推奨：16 文字以上、英数記号混在。例:

```
mac で生成する場合:
$ openssl rand -base64 24
xPj4...（24 文字程度）
```

神山さんが iPhone / iPad / PC ブラウザに記録するだけのものなので、覚える必要なし。

---

## 3. Vercel Dashboard で env var を 3 つ設定

1. <https://vercel.com/dashboard> にログイン → Tribune プロジェクトを開く
2. **Settings** → **Environment Variables**
3. 以下 3 つを追加（Environment は **Production** + **Preview** + **Development** すべて有効に）：

| Name | Value | 用途 |
|---|---|---|
| `TRIBUNE_AUTH_PASSWORD` | 上記で決めたパスワード | コメント入力画面の認証 |
| `TRIBUNE_GITHUB_PAT` | 上記で発行した `github_pat_...` | data/comments/ への commit |
| `TRIBUNE_GITHUB_REPO` | `akiokamiyama-ai/kt-paper-1caa` | デフォルト値と同じだが明示しておくと安全 |

### オプション（必要時のみ）

| Name | Value | 用途 |
|---|---|---|
| `TRIBUNE_GITHUB_BRANCH` | `main` | デフォルト `main`。別ブランチで運用したい場合だけ設定 |

設定後、**Save** → **Redeploy**（Settings → Deployments → 最新を Redeploy）で env var が反映される。

---

## 4. 動作確認

### 4-1. CTA リンク

5/29 以降の朝刊（編集後記が出ている日）を開き、編集後記の最下部に
「コメントを書く →」という小さなリンクが表示されているか確認する。
クリックで `/comment?date=YYYY-MM-DD` に飛ぶ。

> 注：既存 archive HTML は immutable のため CTA は出ない。明日 6/3 の cron
> 生成分から CTA が入る。

### 4-2. パスワード認証

- `/comment?date=2026-06-03` にアクセス（任意の日付）
- パスワード入力 → ログイン
- 成功すると 30 日間有効な HttpOnly Cookie が発行される

### 4-3. 新規投稿

- 認証後、textarea に本文を入力 → **投稿する**
- GitHub に `data/comments/2026-06-03.md` が commit される（`comment: 2026-06-03`）
- リポジトリの commit history で確認できる

### 4-4. 編集（既存コメント）

- 既存コメントがある日付の `/comment?date=...` にアクセス
- textarea に既存内容が prefill される
- 編集して投稿 → 上書き commit（sha 衝突は 1 回 retry で吸収）

### 4-5. 過去コメント閲覧

- `/comments/archive` にアクセス
- パスワード認証 → 日付降順の一覧
- 「閲覧」リンクで本文表示（read-only）
- 当日のみ「編集」リンク表示

---

## 5. レスポンシブ動作確認

| 端末 | ブレークポイント | 期待挙動 |
|---|---|---|
| PC | デフォルト | 820px 中央寄せ、textarea 320px |
| iPad Air (10.9") portrait 820px | `max-width: 834px` 発火 | padding 縮小、textarea 280px |
| iPhone 13 mini 375px | `max-width: 480px` 発火 | 単段組、ボタン拡大、textarea 240px |

C41 第二弾で揃えた 834px / 480px の 2 段ブレークポイントを流用。

---

## 6. トラブルシューティング

### `/api/auth` が 500 を返す
→ `TRIBUNE_AUTH_PASSWORD` 未設定 or 8 文字未満。Vercel Dashboard で確認。

### `/api/comments` POST が 502 を返す
→ `TRIBUNE_GITHUB_PAT` 失効・権限不足。GitHub Settings で PAT のスコープと有効期限を確認。

### Cookie が効かず毎回パスワード要求
→ HttpOnly + Secure + SameSite=Strict なので **HTTPS 必須**。Vercel デプロイなら自動で HTTPS、ローカル開発は localhost で Secure 緩和される（Chrome の挙動）。

### 連投ガード (429)
→ 認証 5 秒 / 投稿 10 秒の連投制限。少し待って再試行。

### パスワード忘れ
→ Vercel Dashboard で `TRIBUNE_AUTH_PASSWORD` を新しい値に更新 → 既存 Cookie も自動で無効化される（HMAC 鍵が変わるため）。

---

## 7. セキュリティモデル

- **公開度**: `X-Robots-Tag: noindex,nofollow` で検索エンジンには出ない
- **認証**: 単一パスワード + HttpOnly Cookie。神山さん 1 ユーザー前提
- **PAT スコープ**: `kt-paper-1caa` の Contents のみ。漏洩しても他リポは影響なし
- **書込パス**: `data/comments/YYYY-MM-DD.md` のみ。他ファイルは API で書けない（path hardcoded）
- **payload 上限**: 16 KB
- **日付バリデーション**: 今日 ±14 日のみ受付（将来日や古い日付の改ざん防止）
- **rate limit**: 同一 IP から認証 5 秒 / 投稿 10 秒の連投ガード

---

## 8. 関連 commits

- 本機能：C37 commit （履歴参照）
- ブレークポイント設計：C41 第二弾 `211019a`
- 編集後記システム：Sprint 4 Phase 3

## 9. 既知の制限 / 将来課題

- 土・日のコメントは `comments_reader.py` の week 読込（日-金のみ）からスキップされる。土曜 AIかみやま応答に取り込まれない（投稿自体は可能）
- 過去 14 日より古い日付への投稿は不可（バリデーション）。必要なら API の `DATE_WINDOW_DAYS` を緩和
- AI 対話機能（C57）は別案件で扱う
