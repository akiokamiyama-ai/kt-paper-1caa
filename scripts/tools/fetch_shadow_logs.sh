#!/usr/bin/env bash
# shadow 評価ログを GHA artifact からまとめて回収する (C215, 2026-10-06).
#
# logs/shadow_eval_*.json は .gitignore 対象で **artifact にしか残らない**。
# 2 週間分を比べるには 1 日ずつ artifact を落として 1 箇所に集める必要がある。
#
# 使い方:
#     bash scripts/tools/fetch_shadow_logs.sh [日数] [出力先]
#     bash scripts/tools/fetch_shadow_logs.sh 14 /tmp/shadow
#     python3 -m scripts.shadow.compare --days 14 --log-dir /tmp/shadow
#
# 注意（C200 の教訓）:
#   ``gh run download`` は **git repo 外で実行すると即座に終了する**
#   （"failed to run git: not a git repository" を出して exit 0）。
#   C196 ではこれを「2 分でタイムアウトした」と誤診し、誤った制約が 2 サイクル
#   引き継がれた。だから必ず --repo を明示する。
set -uo pipefail

DAYS="${1:-14}"
OUT="${2:-/tmp/shadow}"
REPO="akiokamiyama-ai/kt-paper-1caa"

mkdir -p "$OUT"

echo "直近 ${DAYS} 日の shadow ログを ${OUT} に集めます（repo=${REPO}）"

# 日付ごとに「その日最初に成功した run」を選ぶ（= 実作業 run）。
gh run list --workflow=daily.yml --limit $((DAYS * 3)) \
    --json databaseId,createdAt,event,conclusion --repo "$REPO" 2>/dev/null \
  | python3 -c "
import json, sys, collections
from datetime import datetime, timedelta, timezone
JST = timezone(timedelta(hours=9))
by = collections.defaultdict(list)
for r in json.load(sys.stdin):
    if r['conclusion'] != 'success':
        continue
    c = datetime.fromisoformat(r['createdAt'].replace('Z', '+00:00')).astimezone(JST)
    by[c.date().isoformat()].append((c, r['databaseId']))
for d in sorted(by)[-${DAYS}:]:
    print(d, sorted(by[d])[0][1])
" > "$OUT/.runs.txt"

n_ok=0
n_ng=0
while read -r day id; do
    [ -z "${day:-}" ] && continue
    tmp="$OUT/.tmp-$day"
    rm -rf "$tmp"
    if timeout 120 gh run download "$id" --repo "$REPO" \
            -n "audit-logs-$day" -D "$tmp" >/dev/null 2>&1 \
       && [ -f "$tmp/shadow_eval_$day.json" ]; then
        mv "$tmp/shadow_eval_$day.json" "$OUT/"
        n_ok=$((n_ok + 1))
        printf '  OK  %s\n' "$day"
    else
        n_ng=$((n_ng + 1))
        printf '  --  %s （shadow ログなし）\n' "$day"
    fi
    rm -rf "$tmp"
done < "$OUT/.runs.txt"
rm -f "$OUT/.runs.txt"

echo
echo "回収 ${n_ok} 日分 / 無し ${n_ng} 日分 → ${OUT}"
echo
echo "次に:"
echo "  python3 -m scripts.shadow.compare --days ${DAYS} --log-dir ${OUT}"
echo "  python3 -m scripts.shadow.compare --days ${DAYS} --log-dir ${OUT} --divergent 5"
