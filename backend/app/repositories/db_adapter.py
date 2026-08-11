from __future__ import annotations

import mimetypes
import uuid
from datetime import datetime
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.db.models import Asset, ConfigSnapshot, TaskInputAsset, TaskOutputAsset, TaskPrompt, User, WorkflowTask
from backend.app.services.asset_storage import asset_record, decode_data_url, media_kind, safe_filename
from backend.app.services.json_repository import (
    delete_asset_file,
    history_prompt_items,
    hydrate_input_images,
    hydrate_output_asset,
)
from backend.app.services.task_tracking_service import TERMINAL_STATES


class DbStudioRepository:
    """RDS/MySQL-backed adapter with the same response shape as JSON storage.

    Task history (load_history/append_history/delete_history_item) is wired
    into the live app unconditionally via
    backend.app.repositories.factory.history_repository() (D-03) - it does
    not depend on PERSISTENCE_BACKEND. Asset/config/upload methods on this
    class are only reached when PERSISTENCE_BACKEND=db, via
    factory.studio_repository().
    """

    def __init__(self, session: Session, *, uploads_dir: Path, outputs_dir: Path):
        self.session = session
        self.uploads_dir = Path(uploads_dir)
        self.outputs_dir = Path(outputs_dir)

    def load_history(self) -> list[dict]:
        tasks = self.session.scalars(
            select(WorkflowTask)
            # B-05: soft delete된 작업은 제외.
            .where(
                func.upper(WorkflowTask.status).in_({"COMPLETED", "SUCCESS", "FAILED", "TIMED_OUT"}),
                WorkflowTask.deleted_at.is_(None),
            )
            .order_by(WorkflowTask.created_at.desc(), WorkflowTask.id.desc())
        ).all()
        return [self._task_to_history_item(task) for task in tasks]

    def append_history(self, item: dict) -> list[dict]:
        task_id = item.get("taskId") or f"task_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
        user = self._ensure_user(item.get("user") or {}, item.get("workerName"))
        started_at = parse_datetime(item.get("timestamp")) or datetime.utcnow()
        raw_config = item.get("configJson") or item.get("config") or {}
        config = {
            key: value
            for key, value in raw_config.items()
            if str(key).lower() != "seed"
        }
        task = self.session.get(WorkflowTask, task_id)
        if not task:
            task = WorkflowTask(id=task_id, created_at=started_at, updated_at=datetime.utcnow())
            self.session.add(task)
        task.runpod_job_id = item.get("runpodJobId") or None
        task.workflow_id = item.get("workflowId") or item.get("workflowName") or "unknown"
        task.execution_mode = item.get("executionMode") or "dry-run"
        task.status = item.get("status") or "Completed"
        task.progress = int(item.get("progress") or 100)
        task.worker_name = item.get("workerName") or (item.get("user") or {}).get("name") or "-"
        task.user_id = user.id if user else None
        task.started_at = started_at
        task.completed_at = parse_datetime(item.get("completedAt"))
        task.elapsed_seconds = to_int_or_none(item.get("elapsedSeconds"))
        task.positive_prompts = item.get("positivePrompts") or history_prompt_items(item, "positive", item.get("prompt", ""))
        task.negative_prompts = item.get("negativePrompts") or history_prompt_items(item, "negative", item.get("negativePrompt", ""))
        task.config_json = config
        task.wan_node_config = item.get("wanNodeConfig") or {}
        task.patch_summary = item.get("patchSummary") or {}
        sanitized_segments = []
        for segment in item.get("segments") or []:
            if not isinstance(segment, dict):
                sanitized_segments.append(segment)
                continue
            sanitized_segment = dict(segment)
            if isinstance(segment.get("config"), dict):
                sanitized_segment["config"] = {
                    key: value for key, value in segment["config"].items()
                    if str(key).lower() != "seed"
                }
            sanitized_segments.append(sanitized_segment)
        task.payload_json = {
            **item,
            "configJson": config,
            "segments": sanitized_segments,
            "generationSeed": item.get("generationSeed") or item.get("seed"),
        }
        task.runpod_submit_json = item.get("runpodSubmit") or {}
        task.runpod_status_json = item.get("runpodStatus") or {}
        task.updated_at = datetime.utcnow()
        self.session.flush()

        self._replace_task_asset_links(task, item)
        self._ensure_task_prompts(task, item)
        self.session.commit()
        # Completion must not depend on a second full-history DB query.
        return [self._task_to_history_item(task)]

    def delete_history_item(self, task_id: str) -> dict:
        task = self.session.get(WorkflowTask, task_id)
        if not task:
            raise KeyError(task_id)
        # 2026-08-10: 진행 중 작업 삭제 방지 - 3a 화면의 삭제 확인 모달이 항상
        # "진행 중인 작업은 삭제할 수 없습니다"라고 안내했지만 이 함수는 실제로
        # task.status를 확인하지 않고 무조건 삭제해 문구와 동작이 어긋나 있었다.
        # task_tracking_service.TERMINAL_STATES(완료/실패/취소/타임아웃)에 속하지
        # 않으면(즉 대기·진행 중이면) 삭제를 거부한다.
        if str(task.status or "").upper() not in TERMINAL_STATES:
            raise ValueError(f"진행 중인 작업은 삭제할 수 없습니다: {task_id} (status={task.status})")
        # B-05: 하드 삭제 → soft delete. 작업 레코드와 그 프롬프트/자산 링크는 남기고
        # deleted_at만 찍는다. 이력 조회(목록·총계·재사용 프롬프트)는 deleted_at IS NULL만
        # 보므로 사용자에겐 사라진 것으로 보이고, 결과물 파일(assets)은 그대로 남는다
        # (3a "결과물 파일은 Assets에 남습니다"). 이미 삭제된 작업의 재삭제는 멱등 처리.
        if task.deleted_at is None:
            task.deleted_at = datetime.utcnow()
            self.session.commit()
        return {
            "deleted": True,
            "taskId": task_id,
            "softDeleted": True,
            "removedAssets": [],
            "fileResults": [],
        }

    def load_configs(self) -> list[dict]:
        rows = self.session.scalars(
            select(ConfigSnapshot).order_by(ConfigSnapshot.created_at.desc(), ConfigSnapshot.id.desc())
        ).all()
        return [self._config_to_json(row) for row in rows]

    def append_config(self, item: dict) -> list[dict]:
        config_id = item.get("configId") or item.get("id") or f"config_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
        user = self._ensure_user(item.get("user") or (item.get("snapshot") or {}).get("user") or {}, None)
        row = self.session.get(ConfigSnapshot, config_id)
        if not row:
            row = ConfigSnapshot(id=config_id)
            self.session.add(row)
        snapshot = item.get("snapshot") or item
        row.workflow_id = item.get("workflowId") or snapshot.get("workflowId") or "unknown"
        row.name = item.get("name") or f"{Path(row.workflow_id).stem} saved config"
        row.source = item.get("source") or "studio"
        row.user_id = user.id if user else None
        row.snapshot_json = item
        row.created_at = parse_datetime(item.get("timestamp")) or datetime.utcnow()
        self.session.commit()
        return self.load_configs()

    def create_upload(self, payload: dict) -> dict:
        file_name = safe_filename(payload.get("fileName"))
        raw, mime_type = decode_data_url(payload.get("dataUrl", ""))
        if len(raw) == 0:
            raise ValueError("uploaded file is empty")
        asset_id = f"asset_{uuid.uuid4().hex[:12]}"
        stored_name = f"{asset_id}_{file_name}"
        path = self.uploads_dir / stored_name
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("wb") as stream:
            stream.write(raw)
        item = {
            "assetId": asset_id,
            "type": "input_image",
            "fileName": file_name,
            "mimeType": payload.get("mimeType") or mime_type,
            "sizeBytes": len(raw),
            "path": str(path),
            "createdAt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        self._upsert_asset_from_json(item)
        self.session.commit()
        return item

    def get_asset(self, asset_id: str):
        asset = self.session.get(Asset, asset_id)
        if not asset:
            raise KeyError(asset_id)
        path = Path(asset.storage_key)
        if asset.storage_backend != "local" or not path.exists() or not path.is_file():
            raise FileNotFoundError(asset_id)
        return self._asset_to_json(asset), path

    def register_asset(self, file_path, asset_type: str, mime_type: str | None = None, file_name: str | None = None) -> dict:
        item = asset_record(Path(file_path), asset_type, mime_type, file_name)
        self._upsert_asset_from_json(item)
        self.session.commit()
        return item

    def upsert_asset_record(self, item: dict) -> dict:
        asset = self._upsert_asset_from_json(item)
        self.session.commit()
        return self._asset_to_json(asset)

    def hydrate_input_images(self, item: dict) -> list[dict]:
        return hydrate_input_images(item, self._assets_by_id())

    def _ensure_user(self, user_payload: dict, fallback_name: str | None) -> User | None:
        user_id = str(user_payload.get("id") or user_payload.get("email") or "").strip()
        if not user_id:
            return None
        user = self.session.get(User, user_id)
        is_new_user = user is None
        if not user:
            user = User(id=user_id, created_at=datetime.utcnow(), updated_at=datetime.utcnow())
            self.session.add(user)
        user.name = user_payload.get("name") or fallback_name or user_id
        user.email = user_payload.get("email")
        # 2026-08-11 버그 수정: 이 메서드는 Job 이력·설정을 저장할 때 FK를 만족시키기
        # 위해 호출되며(append_history/append_config), 사용자가 제출 버튼을 누른
        # "그 시점"의 브라우저 세션 role 스냅샷을 payload로 받는다. 예전엔 role을
        # 매번 무조건 덮어써서, 관리자가 그 사이 사용자를 승격(예: SUPER_ADMIN)시켜도
        # 제출됐던 Job이 나중에 완료되어 이 함수가 다시 호출되면 role이 제출 당시의
        # 옛 값으로 조용히 되돌아갔다. role은 admin_service.upsert_admin_user()(관리자
        # 역할 변경 API)에서만 바뀌어야 하므로, 신규 사용자 최초 생성 시에만 반영한다.
        if is_new_user:
            user.role = user_payload.get("role") or "operator"
        user.updated_at = datetime.utcnow()
        return user

    def _upsert_asset_from_json(self, item: dict) -> Asset:
        asset_id = item.get("assetId") or item.get("id")
        if not asset_id:
            raise ValueError("assetId is required")
        file_name = item.get("fileName") or item.get("filename") or Path(item.get("path") or asset_id).name
        mime_type = item.get("mimeType") or mimetypes.guess_type(file_name)[0] or "application/octet-stream"
        asset = self.session.get(Asset, asset_id)
        if not asset:
            asset = Asset(id=asset_id)
            self.session.add(asset)
        asset.asset_type = item.get("type") or item.get("assetType") or "asset"
        asset.file_name = file_name
        asset.mime_type = mime_type
        asset.size_bytes = int(item.get("sizeBytes") or 0)
        asset.storage_backend = item.get("storageBackend") or "local"
        asset.storage_key = item.get("path") or item.get("storageKey") or ""
        asset.public_url = item.get("publicUrl")
        asset.metadata_json = {
            key: value
            for key, value in item.items()
            if key not in {"assetId", "id", "type", "assetType", "fileName", "filename", "mimeType", "sizeBytes", "path", "storageKey", "storageBackend", "publicUrl", "createdAt"}
        }
        asset.created_at = parse_datetime(item.get("createdAt")) or datetime.utcnow()
        return asset

    def _replace_task_asset_links(self, task: WorkflowTask, item: dict) -> None:
        for link in list(task.input_assets):
            self.session.delete(link)
        for link in list(task.output_assets):
            self.session.delete(link)
        self.session.flush()

        for index, asset_id in enumerate(input_asset_ids(item), start=1):
            if self.session.get(Asset, asset_id):
                self.session.add(TaskInputAsset(task_id=task.id, asset_id=asset_id, slot_index=index))

        for asset in item.get("outputAssets") or []:
            if not isinstance(asset, dict):
                continue
            asset_id = asset.get("assetId")
            if not asset_id:
                continue
            if not self.session.get(Asset, asset_id):
                self._upsert_asset_from_json(asset)
            self.session.add(TaskOutputAsset(
                task_id=task.id,
                asset_id=asset_id,
                output_role=asset.get("outputRole") or "final",
                segment_index=to_int_or_none(asset.get("segmentIndex")),
            ))

    def _ensure_task_prompts(self, task: WorkflowTask, item: dict) -> None:
        if task.prompts:
            return
        segments = item.get("segments") if isinstance(item.get("segments"), list) else []
        positives = item.get("positivePrompts") or history_prompt_items(item, "positive", item.get("prompt", ""))
        negatives = item.get("negativePrompts") or history_prompt_items(item, "negative", item.get("negativePrompt", ""))
        segment_count = max(
            1,
            to_int_or_none(item.get("segmentCount")) or 0,
            len(segments),
            len(positives),
            len(negatives),
        )
        input_ids = input_asset_ids(item)
        output_assets = [asset for asset in item.get("outputAssets") or [] if isinstance(asset, dict)]
        final_ids = [asset.get("assetId") for asset in output_assets if asset.get("outputRole") == "final" and asset.get("assetId")]

        for index in range(1, segment_count + 1):
            segment = _find_indexed_item(segments, index) or {}
            positive = (
                segment.get("positivePrompt")
                or _find_prompt_text(positives, index)
                or item.get("prompt")
                or ""
            )
            negative = (
                segment.get("negativePromptAddition")
                or segment.get("negativePrompt")
                or _find_prompt_text(negatives, index)
                or item.get("negativePrompt")
                or ""
            )
            config = segment.get("config") or task.config_json or {}
            output_ids = [
                asset.get("assetId")
                for asset in output_assets
                if asset.get("assetId")
                and (
                    to_int_or_none(asset.get("segmentIndex")) == index
                    or (segment_count == 1 and asset.get("outputRole") == "final")
                )
            ] or final_ids
            self.session.add(TaskPrompt(
                task_id=task.id,
                workflow_id=task.workflow_id,
                segment_index=index,
                model_name=_segment_model_name(segment, config),
                positive_prompt=str(positive or ""),
                negative_prompt=str(negative or ""),
                input_asset_ids=input_ids,
                output_asset_ids=output_ids,
                quality_rating=None,
                quality_comment=None,
                reuse_count=0,
                metadata_json={
                    "source": "history_migration",
                    "segment": segment,
                    "config": config,
                    "workflowId": task.workflow_id,
                    "runpodJobId": task.runpod_job_id,
                },
            ))

    def _asset_has_task_refs(self, asset_id: str) -> bool:
        input_ref = self.session.scalar(
            select(TaskInputAsset.id).where(TaskInputAsset.asset_id == asset_id).limit(1)
        )
        output_ref = self.session.scalar(
            select(TaskOutputAsset.id).where(TaskOutputAsset.asset_id == asset_id).limit(1)
        )
        return input_ref is not None or output_ref is not None

    def _task_to_history_item(self, task: WorkflowTask) -> dict:
        item = dict(task.payload_json or {})
        item.setdefault("taskId", task.id)
        item.setdefault("timestamp", format_datetime(task.started_at or task.created_at))
        item.setdefault("workflowId", task.workflow_id)
        item.setdefault("workflowName", task.workflow_id)
        item.setdefault("runpodJobId", task.runpod_job_id or "")
        item.setdefault("executionMode", task.execution_mode)
        item.setdefault("workerName", task.worker_name or "-")
        item.setdefault("status", task.status)
        item.setdefault("positivePrompts", task.positive_prompts or [])
        item.setdefault("negativePrompts", task.negative_prompts or [])
        item.setdefault("configJson", task.config_json or {})
        item.setdefault("wanNodeConfig", task.wan_node_config or {})
        item.setdefault("patchSummary", task.patch_summary or {})
        item.setdefault(
            "generationSeed",
            ((task.patch_summary or {}).get("seed") or {}).get("value"),
        )
        item.setdefault("inputAssets", [link.asset_id for link in sorted(task.input_assets, key=lambda link: link.slot_index)])
        item["outputAssets"] = [
            hydrate_output_asset(
                {
                    **self._asset_to_json(link.asset),
                    "outputRole": link.output_role,
                    "segmentIndex": link.segment_index,
                },
                {link.asset_id: self._asset_to_json(link.asset)},
            )
            for link in sorted(task.output_assets, key=lambda link: (link.segment_index or 0, link.id or 0))
        ] or item.get("outputAssets", [])
        item["inputImages"] = item.get("inputImages") or hydrate_input_images(item, self._assets_by_id())
        item["wanNodeConfig"] = item.get("wanNodeConfig") or {}
        return item

    def _config_to_json(self, row: ConfigSnapshot) -> dict:
        item = dict(row.snapshot_json or {})
        item.setdefault("configId", row.id)
        item.setdefault("timestamp", format_datetime(row.created_at))
        item.setdefault("source", row.source)
        item.setdefault("workflowId", row.workflow_id)
        item.setdefault("name", row.name)
        return item

    def _asset_to_json(self, asset: Asset) -> dict:
        item = dict(asset.metadata_json or {})
        item.update({
            "assetId": asset.id,
            "type": asset.asset_type,
            "fileName": asset.file_name,
            "mimeType": asset.mime_type,
            "sizeBytes": asset.size_bytes,
            "path": asset.storage_key,
            "createdAt": format_datetime(asset.created_at),
        })
        item.setdefault("kind", media_kind(asset.file_name, asset.mime_type, item.get("kind")))
        item.setdefault("downloadUrl", f"/api/files/{asset.id}")
        return item

    def _assets_by_id(self) -> dict:
        return {asset.id: self._asset_to_json(asset) for asset in self.session.scalars(select(Asset)).all()}


def parse_datetime(value) -> datetime | None:
    if isinstance(value, datetime):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    for pattern in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f"):
        try:
            return datetime.strptime(text.removesuffix("Z"), pattern)
        except ValueError:
            continue
    return None


def format_datetime(value: datetime | None) -> str:
    return (value or datetime.utcnow()).strftime("%Y-%m-%d %H:%M:%S")


def to_int_or_none(value) -> int | None:
    try:
        if value is None or value == "":
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def input_asset_ids(item: dict) -> list[str]:
    result = []

    def add(value) -> None:
        text = str(value or "").strip()
        if text and text not in result:
            result.append(text)

    for asset_id in item.get("inputAssets") or []:
        add(asset_id)
    for image in item.get("inputImages") or []:
        if isinstance(image, dict):
            add(image.get("assetId"))
    for keyframe in item.get("keyframes") or []:
        if isinstance(keyframe, dict):
            add(keyframe.get("uploadId"))
    return result


def _find_indexed_item(items: list, index: int) -> dict | None:
    for item in items:
        if isinstance(item, dict) and to_int_or_none(item.get("index") or item.get("segmentIndex")) == index:
            return item
    if 1 <= index <= len(items) and isinstance(items[index - 1], dict):
        return items[index - 1]
    return None


def _find_prompt_text(items: list, index: int) -> str:
    item = _find_indexed_item(items, index)
    if not item:
        return ""
    return str(item.get("text") or item.get("prompt") or item.get("positivePrompt") or item.get("negativePrompt") or "")


def _segment_model_name(segment: dict, config: dict) -> str | None:
    for key in ("modelName", "model", "checkpoint", "diffusionModel", "vae", "lora"):
        value = segment.get(key) or config.get(key)
        if value:
            return str(value)
    return None
