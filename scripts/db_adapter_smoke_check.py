#!/usr/bin/env python3
"""Smoke check for the DB-backed repository adapter.

This uses a temporary SQLite database with the same Alembic migration scripts.
The production target remains MySQL/RDS, but SQLite keeps this adapter contract
test fast and isolated from local Docker state.
"""

from __future__ import annotations

import base64
import os
import sys
import tempfile
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.repositories.db_adapter import DbStudioRepository  # noqa: E402


def migrate(database_url: str) -> None:
    os.environ["DATABASE_URL"] = database_url
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    command.upgrade(config, "head")


def data_url(raw: bytes, mime_type: str = "image/png") -> str:
    encoded = base64.b64encode(raw).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="dobedub-db-adapter-") as tmp:
        root = Path(tmp)
        database_path = root / "adapter.db"
        database_url = f"sqlite:///{database_path}"
        migrate(database_url)

        engine = create_engine(database_url, future=True)
        Session = sessionmaker(bind=engine, future=True)
        session = Session()
        uploads_dir = root / "uploads"
        outputs_dir = root / "outputs"
        repo = DbStudioRepository(session, uploads_dir=uploads_dir, outputs_dir=outputs_dir)

        png_1x1 = base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQIHWP4z8DwHwAFgAI/"
            "mR4L9wAAAABJRU5ErkJggg=="
        )
        upload = repo.create_upload({
            "fileName": "sample.png",
            "mimeType": "image/png",
            "dataUrl": data_url(png_1x1),
        })
        assert upload["assetId"].startswith("asset_")
        assert upload["imageWidth"] == 1
        assert upload["imageHeight"] == 1
        _, upload_path = repo.get_asset(upload["assetId"])
        assert upload_path.exists()

        outputs_dir.mkdir(parents=True, exist_ok=True)
        output_path = outputs_dir / "sample_1key_000001.mp4"
        output_path.write_bytes(b"sample-video")
        output = repo.register_asset(output_path, "output_image", "video/mp4", "sample_1key_000001.mp4")

        history_item = {
            "taskId": "task_db_adapter_smoke",
            "timestamp": "2026-08-02 12:00:00",
            "workflowId": "1-images.json",
            "workflowName": "1-images.json",
            "runpodJobId": "runpod-db-adapter-smoke",
            "executionMode": "runpod",
            "user": {"id": "user_db_adapter", "name": "DB Adapter User"},
            "workerName": "DB Adapter User",
            "status": "Completed",
            "prompt": "positive smoke prompt",
            "positivePrompt": "1: positive smoke prompt",
            "negativePrompt": "1: negative smoke prompt",
            "positivePrompts": [{"index": 1, "text": "positive smoke prompt"}],
            "negativePrompts": [{"index": 1, "text": "negative smoke prompt"}],
            "segmentCount": 1,
            "configJson": {"fps": 16, "steps": 4, "cfgScale": 1, "motionShift": 5},
            "generationSeed": 1234,
            "wanNodeConfig": {"segments": [{"index": 1, "nodes": {"sampler": {"steps": 4}}}]},
            "outputAssets": [{
                "assetId": output["assetId"],
                "fileName": output["fileName"],
                "mimeType": output["mimeType"],
                "downloadUrl": f"/api/files/{output['assetId']}",
                "outputRole": "final",
                "segmentIndex": 1,
            }],
            "inputAssets": [upload["assetId"]],
            "inputImages": [{
                "index": 1,
                "assetId": upload["assetId"],
                "fileName": upload["fileName"],
                "sizeBytes": upload["sizeBytes"],
                "imageWidth": upload["imageWidth"],
                "imageHeight": upload["imageHeight"],
            }],
            "keyframes": [{"index": 1, "uploadId": upload["assetId"], "fileName": upload["fileName"]}],
            "segments": [{
                "index": 1,
                "positivePrompt": "positive smoke prompt",
                "negativePromptAddition": "negative smoke prompt",
                "config": {"fps": 16, "steps": 4, "cfgScale": 1, "motionShift": 5},
            }],
            "patchSummary": {"images": [{"node": "1", "image": "sample.png"}]},
        }
        history = repo.append_history(history_item)
        assert history[0]["taskId"] == history_item["taskId"]
        assert history[0]["inputImages"][0]["assetId"] == upload["assetId"]
        assert history[0]["inputImages"][0]["imageWidth"] == 1
        assert history[0]["inputImages"][0]["imageHeight"] == 1
        assert history[0]["outputAssets"][0]["assetId"] == output["assetId"]
        assert history[0]["wanNodeConfig"]["segments"][0]["nodes"]["sampler"]["steps"] == 4
        assert history[0]["generationSeed"] == 1234
        assert "seed" not in history[0]["configJson"]

        configs = repo.append_config({
            "configId": "config_db_adapter_smoke",
            "timestamp": "2026-08-02 12:01:00",
            "source": "studio",
            "workflowId": "1-images.json",
            "user": {"id": "user_db_adapter", "name": "DB Adapter User"},
            "name": "adapter smoke config",
            "snapshot": {"workflowId": "1-images.json", "keyframes": history_item["keyframes"]},
        })
        assert configs[0]["configId"] == "config_db_adapter_smoke"

        deleted = repo.delete_history_item(history_item["taskId"])
        assert deleted["deleted"] is True
        assert deleted["softDeleted"] is True
        assert not repo.load_history()
        # Task History uses soft delete so its input/output assets remain
        # available from Asset management after a task record is hidden.
        assert upload_path.exists()
        assert output_path.exists()
        session.close()
        engine.dispose()

    print("OK db adapter smoke check passed")


if __name__ == "__main__":
    main()
