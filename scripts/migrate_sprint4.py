"""Sprint 4 layout swap data migration.

Swaps key names in ``logs/displayed_urls_*.json`` to match the new layout:

* old ``page5_urls`` (dict, leisure 3 areas) → new ``page6_urls``
* old ``page6_url`` (single, serendipity)   → new ``page5_url``

Also renames the disk file ``logs/page6_history.json`` →
``logs/page5_history.json`` since the serendipity selector now lives in
the page5 directory.

Backups are written as ``*.bak`` next to each modified file (logs/ is
gitignored, so backups are the only rollback path).

Usage::

    python3 scripts/migrate_sprint4.py             # 実変換
    python3 scripts/migrate_sprint4.py --dry-run   # ドライラン

Idempotent: re-running is safe — files already in the new format are
skipped.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

LOGS_DIR = Path(__file__).resolve().parent.parent / "logs"
DRY_RUN = "--dry-run" in sys.argv


def main() -> int:
    print(f"[migrate_sprint4] dry_run={DRY_RUN}")
    print(f"[migrate_sprint4] LOGS_DIR={LOGS_DIR}")

    # 1) displayed_urls_*.json: page5_urls ↔ page6_url を入れ替え
    converted = 0
    skipped = 0
    for log_file in sorted(LOGS_DIR.glob("displayed_urls_*.json")):
        try:
            data = json.loads(log_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            print(f"  {log_file.name}: read error ({e}), skip")
            continue

        # Idempotency: 既に新形式なら skip
        if "page5_url" in data or "page6_urls" in data:
            print(f"  {log_file.name}: already in new format, skip")
            skipped += 1
            continue

        old_p5 = data.pop("page5_urls", None)
        old_p6 = data.pop("page6_url", None)

        if old_p6 is not None:
            data["page5_url"] = old_p6
        if old_p5 is not None:
            data["page6_urls"] = old_p5

        if DRY_RUN:
            print(
                f"  [dry-run] would convert {log_file.name} "
                f"(had page5_urls={old_p5 is not None}, "
                f"page6_url={old_p6 is not None})"
            )
        else:
            backup = log_file.with_suffix(".json.bak")
            shutil.copy(log_file, backup)
            log_file.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            print(f"  converted {log_file.name} (backup: {backup.name})")
            converted += 1

    print(f"[migrate_sprint4] displayed_urls: {converted} converted, {skipped} skipped")

    # 2) page6_history.json → page5_history.json (file rename)
    old_h = LOGS_DIR / "page6_history.json"
    new_h = LOGS_DIR / "page5_history.json"

    if old_h.exists() and not new_h.exists():
        if DRY_RUN:
            print(f"  [dry-run] would rename {old_h.name} → {new_h.name}")
        else:
            shutil.copy(old_h, old_h.with_suffix(".json.bak"))
            old_h.rename(new_h)
            print(f"  renamed {old_h.name} → {new_h.name} (backup: {old_h.name}.bak)")
    elif old_h.exists() and new_h.exists():
        print(
            f"  WARN: both {old_h.name} and {new_h.name} exist — "
            "manual review needed",
        )
    elif not old_h.exists() and new_h.exists():
        print(f"  {new_h.name} already exists, {old_h.name} not present, skip")
    else:
        print(f"  {old_h.name} does not exist, skip")

    print("[migrate_sprint4] done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
