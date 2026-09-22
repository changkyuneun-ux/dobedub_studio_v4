from __future__ import annotations

import argparse
import json

from backend.app.core.config import get_settings
from backend.app.db.session import SessionLocal
from backend.app.services.workflow_import_service import apply_workflow_import, plan_workflow_import


def main() -> int:
    parser = argparse.ArgumentParser(description="Import workflow file metadata into RDS")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    settings = get_settings()
    with SessionLocal() as db:
        plan = plan_workflow_import(db, settings.workflows_dir, settings.workflow_seed_dir, settings.data_dir)
        if args.dry_run:
            result = {
                "mode": "dry-run",
                "items": [
                    {"workflowId": item.workflow_id, "source": item.source, "status": item.status}
                    for item in plan.items
                ],
            }
        else:
            result = {"mode": "apply", **apply_workflow_import(db, plan)}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
