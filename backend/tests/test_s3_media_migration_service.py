from __future__ import annotations

from pathlib import Path

from backend.app.db.models import Asset, BatchJob, ImagePromptDraft, TaskInputAsset, TaskOutputAsset, User, WorkflowTask
from backend.app.services import s3_media_migration_service


def test_migrate_local_batch_input_and_output_assets_to_s3(db_session, tmp_path, monkeypatch):
    input_path = tmp_path / "input.png"
    output_path = tmp_path / "output.mp4"
    input_path.write_bytes(b"png")
    output_path.write_bytes(b"mp4")

    db_session.add(User(id="operator", name="operator", role="OPERATOR"))
    db_session.add(BatchJob(id="batch_1", workflow_id="wan.json", status="COMPLETE", total_images=1, created_by="operator"))
    db_session.add_all([
        Asset(
            id="asset_input",
            asset_type="input_image",
            file_name="scene.png",
            mime_type="image/png",
            size_bytes=3,
            storage_backend="local",
            storage_key=str(input_path),
            metadata_json={},
        ),
        Asset(
            id="asset_output",
            asset_type="output_image",
            file_name="final.mp4",
            mime_type="video/mp4",
            size_bytes=3,
            storage_backend="local",
            storage_key=str(output_path),
            metadata_json={},
        ),
        ImagePromptDraft(
            id="draft_1",
            asset_id="asset_input",
            workflow_id="wan.json",
            slot_index=1,
            provider="grok",
            model="grok",
            positive_prompt="prompt",
            raw_json={"requestItemId": "item_0007"},
            created_by="operator",
            batch_job_id="batch_1",
        ),
        WorkflowTask(
            id="task_1",
            workflow_id="wan.json",
            status="COMPLETED",
            user_id="operator",
            batch_job_id="batch_1",
            request_item_id="item_0007",
            prompt_draft_id="draft_1",
        ),
    ])
    db_session.add(TaskInputAsset(task_id="task_1", asset_id="asset_input", slot_index=1))
    db_session.add(TaskOutputAsset(task_id="task_1", asset_id="asset_output", output_role="final"))
    db_session.commit()

    class FakeStorage:
        def __init__(self):
            self.saved: dict[str, bytes] = {}
            self.bucket = "dobedub-studio-local"

        def save_file(self, key, source_path, *, file_name=None, mime_type=None):
            storage_key = f"local/{key}"
            self.saved[storage_key] = Path(source_path).read_bytes()
            return type("Stored", (), {
                "storage_key": storage_key,
                "public_url": f"s3://dobedub-studio-local/{storage_key}",
            })()

    fake = FakeStorage()
    monkeypatch.setenv("S3_PREFIX", "local")
    monkeypatch.setenv("S3_BUCKET", "dobedub-studio-local")
    monkeypatch.setattr(s3_media_migration_service, "s3_asset_storage", lambda: fake)

    result = s3_media_migration_service.migrate_local_media_to_s3(db_session, apply=True)

    assert result.scanned == 2
    assert result.migrated == 2
    assert result.missing == 0
    assert fake.saved == {
        "local/batches/batch_1/items/item_0007/jobs/task_1/inputs/asset_input/scene.png": b"png",
        "local/batches/batch_1/items/item_0007/jobs/task_1/outputs/asset_output/final.mp4": b"mp4",
    }
    assert db_session.get(Asset, "asset_input").storage_backend == "s3"
    assert db_session.get(Asset, "asset_output").storage_backend == "s3"


def test_migrate_local_media_dry_run_does_not_update_db_or_s3(db_session, tmp_path, monkeypatch):
    input_path = tmp_path / "input.png"
    input_path.write_bytes(b"png")
    db_session.add(Asset(
        id="asset_dry",
        asset_type="input_image",
        file_name="scene.png",
        mime_type="image/png",
        size_bytes=3,
        storage_backend="local",
        storage_key=str(input_path),
        metadata_json={},
    ))
    db_session.commit()

    def fail_if_called():
        raise AssertionError("dry-run must not instantiate S3 storage")

    monkeypatch.setattr(s3_media_migration_service, "s3_asset_storage", fail_if_called)

    result = s3_media_migration_service.migrate_local_media_to_s3(db_session, apply=False)

    assert result.scanned == 1
    assert result.migrated == 1
    assert db_session.get(Asset, "asset_dry").storage_backend == "local"
