from __future__ import annotations

from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.db.models import Asset, ImagePromptDraft, TaskInputAsset


def delete_unsubmitted_upload(session: Session, asset_id: str, *, created_by: str) -> dict[str, object]:
    """Delete an unused input upload while protecting prompt and task history."""
    asset = session.get(Asset, asset_id)
    if not asset:
        raise KeyError(asset_id)
    if asset.asset_type != "input_image":
        raise ValueError("업로드한 입력 이미지만 삭제할 수 있습니다.")

    owner_id = str((asset.metadata_json or {}).get("createdBy") or "").strip()
    if owner_id and owner_id != created_by:
        raise PermissionError("다른 사용자가 업로드한 이미지는 삭제할 수 없습니다.")

    draft_exists = session.scalar(select(ImagePromptDraft.id).where(ImagePromptDraft.asset_id == asset_id).limit(1))
    task_link_exists = session.scalar(select(TaskInputAsset.id).where(TaskInputAsset.asset_id == asset_id).limit(1))
    if draft_exists or task_link_exists:
        raise ValueError("프롬프트 생성 또는 RunPod 작업에 연결된 이미지는 삭제할 수 없습니다.")

    local_path = Path(asset.storage_key) if asset.storage_backend == "local" else None
    session.delete(asset)
    session.commit()
    if local_path:
        try:
            local_path.unlink(missing_ok=True)
        except OSError:
            # The database entry is already removed. A later storage cleanup can
            # safely handle an inaccessible orphan without breaking the UI flow.
            pass
    return {"assetId": asset_id, "deleted": True}
