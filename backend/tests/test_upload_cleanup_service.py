from __future__ import annotations

from pathlib import Path

import pytest

from backend.app.db.models import Asset, ImagePromptDraft
from backend.app.services.upload_cleanup_service import delete_unsubmitted_upload


def _upload(asset_id: str, path: Path) -> Asset:
    return Asset(
        id=asset_id,
        asset_type="input_image",
        file_name=path.name,
        mime_type="image/png",
        size_bytes=path.stat().st_size,
        storage_backend="local",
        storage_key=str(path),
        metadata_json={"createdBy": "worker_a"},
    )


def test_delete_unsubmitted_upload_removes_database_record_and_local_file(db_session, tmp_path):
    path = tmp_path / "unsubmitted.png"
    path.write_bytes(b"image")
    db_session.add(_upload("asset_unsubmitted", path))
    db_session.commit()

    result = delete_unsubmitted_upload(db_session, "asset_unsubmitted", created_by="worker_a")

    assert result == {"assetId": "asset_unsubmitted", "deleted": True}
    assert db_session.get(Asset, "asset_unsubmitted") is None
    assert not path.exists()


def test_delete_unsubmitted_upload_rejects_drafts_already_created(db_session, tmp_path):
    path = tmp_path / "draft-linked.png"
    path.write_bytes(b"image")
    db_session.add(_upload("asset_draft_linked", path))
    db_session.add(ImagePromptDraft(
        id="draft_linked",
        asset_id="asset_draft_linked",
        workflow_id="1-images.json",
        slot_index=1,
        status="PENDING",
        provider="grok",
        model="grok-test",
        instruction_version="wf@1",
        warnings_json=[],
        raw_json={},
        created_by="worker_a",
    ))
    db_session.commit()

    with pytest.raises(ValueError, match="프롬프트 생성 또는 RunPod 작업"):
        delete_unsubmitted_upload(db_session, "asset_draft_linked", created_by="worker_a")

    assert db_session.get(Asset, "asset_draft_linked") is not None
    assert path.exists()
