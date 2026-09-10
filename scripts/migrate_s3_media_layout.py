#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from backend.app.db.session import SessionLocal
from backend.app.services.s3_media_migration_service import migrate_s3_media_to_final_layout


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Move existing S3 media asset rows from legacy S3 prefixes into the final batch-scoped layout."
    )
    parser.add_argument("--apply", action="store_true", help="Copy S3 objects and update asset rows. Omit for dry-run.")
    parser.add_argument("--delete-source", action="store_true", help="Delete old S3 objects after successful copy. Default keeps old objects.")
    parser.add_argument("--limit", type=int, default=None, help="Maximum number of S3 media assets to scan.")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        result = migrate_s3_media_to_final_layout(
            db,
            apply=args.apply,
            delete_source=args.delete_source,
            limit=args.limit,
        )
        print(json.dumps(result.__dict__, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:  # noqa: BLE001 - top-level CLI error presentation
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
