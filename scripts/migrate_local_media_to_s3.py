#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys

from backend.app.db.session import SessionLocal
from backend.app.services.s3_media_migration_service import migrate_local_media_to_s3


def main() -> int:
    parser = argparse.ArgumentParser(description="Migrate local input/output media assets to S3.")
    parser.add_argument("--apply", action="store_true", help="Upload files to S3 and update asset rows. Omit for dry-run.")
    parser.add_argument("--limit", type=int, default=None, help="Maximum number of local media assets to scan.")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        result = migrate_local_media_to_s3(db, apply=args.apply, limit=args.limit)
        print(json.dumps(result.__dict__, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:  # noqa: BLE001 - top-level CLI error presentation
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
