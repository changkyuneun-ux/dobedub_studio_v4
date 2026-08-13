from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path
from threading import RLock

from backend.app.core.config import get_settings
from backend.app.repositories.factory import data_paths, history_repository, studio_repository
from backend.app.services import job_service, output_service, workflow_patch_service
from backend.app.services.asset_storage import encode_file_base64, safe_filename
from backend.app.services.runpod_client import connection_status as runpod_connection_status
from backend.app.services.runpod_client import runpod_request as runpod_client_request
from backend.app.services.task_tracking_service import (
    active_task_ids,
    assets_total,
    list_assets,
    record_job_status,
    restore_job_from_task,
    reusable_task_prompts,
    task_history_items,
    task_history_total,
    task_prompts,
    update_task_prompt_quality,
    update_task_prompt_review,
)
from backend.app.services.task_policy_service import assert_task_submission_allowed
from backend.app.db.session import SessionLocal


JOBS: dict[str, dict] = {}
JOB_LOCK = RLock()


def ensure_storage_dirs() -> None:
    settings = get_settings()
    paths = data_paths()
    for key in ("uploads", "outputs", "reports"):
        paths[key].mkdir(parents=True, exist_ok=True)
    settings.workflows_dir.mkdir(parents=True, exist_ok=True)
    settings.metadata_dir.mkdir(parents=True, exist_ok=True)


def load_history() -> list[dict]:
    # Task history is DB-only (D-03): always read through task_tracking_service,
    # independent of PERSISTENCE_BACKEND (which still governs assets/configs/
    # uploads via studio_repository()).
    return task_history_items()


def paginated_history(page: int = 1, page_size: int = 20) -> dict:
    page = max(1, int(page or 1))
    page_size = max(1, min(200, int(page_size or 20)))
    return {
        "items": task_history_items(page, page_size),
        "page": page,
        "pageSize": page_size,
        "total": task_history_total(),
    }


def append_history(item: dict) -> list[dict]:
    # Task history is DB-only (D-03): bypasses PERSISTENCE_BACKEND on purpose.
    with history_repository() as repository:
        return repository.append_history(item)


def delete_history_item(task_id: str) -> dict:
    # Task history is DB-only (D-03): bypasses PERSISTENCE_BACKEND on purpose.
    with history_repository() as repository:
        return repository.delete_history_item(task_id)


def paginated_assets(
    page: int = 1,
    page_size: int = 20,
    *,
    asset_type: str = "",
    workflow_id: str = "",
    date_from: str = "",
    date_to: str = "",
    collection_id: int | None = None,
    uncategorized: bool = False,
) -> dict:
    # A-01: history와 동일하게 DB 전용(D-03 선례). PERSISTENCE_BACKEND=json에서는
    # task_output_assets 조인 대상이 비어 있을 수 있으나, 운영 환경은 항상
    # PERSISTENCE_BACKEND=db이므로(docs/aws-ecs-deployment.md) 실사용 경로와는 무관.
    page = max(1, int(page or 1))
    page_size = max(1, min(200, int(page_size or 20)))
    filters = dict(
        asset_type=asset_type,
        workflow_id=workflow_id,
        date_from=date_from,
        date_to=date_to,
        collection_id=collection_id,
        uncategorized=uncategorized,
    )
    return {
        "items": list_assets(page, page_size, **filters),
        "page": page,
        "pageSize": page_size,
        "total": assets_total(**filters),
    }


def load_configs() -> list[dict]:
    with studio_repository() as repository:
        return repository.load_configs()


def append_config(item: dict) -> list[dict]:
    with studio_repository() as repository:
        return repository.append_config(item)


def create_config_snapshot(payload: dict) -> dict:
    source = payload.get("source") or "studio"
    snapshot = payload.get("snapshot") or {}
    workflow_id = snapshot.get("workflowId") or payload.get("workflowId") or "unknown"
    config_id = f"config_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
    item = {
        "configId": config_id,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "source": source,
        "workflowId": workflow_id,
        "user": payload.get("user") or snapshot.get("user") or {},
        "name": payload.get("name") or f"{Path(workflow_id).stem} saved config",
        "snapshot": snapshot,
    }
    append_config(item)
    return item


def prompt_options() -> dict:
    history = load_history()
    configs = load_configs()
    options = {"positive": [], "negative": []}

    def add_option(kind, text, label, source, workflow_id="", segment_index=None):
        cleaned = str(text or "").strip()
        if not cleaned:
            return
        option_id = f"{kind}_{uuid.uuid5(uuid.NAMESPACE_URL, f'{kind}:{source}:{label}:{cleaned}').hex[:12]}"
        if any(item["text"] == cleaned and item["label"] == label for item in options[kind]):
            return
        options[kind].append({
            "id": option_id,
            "label": label,
            "text": cleaned,
            "source": source,
            "workflowId": workflow_id,
            "segmentIndex": segment_index,
        })

    for item in history:
        workflow_id = item.get("workflowId") or item.get("workflowName") or item.get("workflow") or ""
        timestamp = item.get("timestamp") or "-"
        for prompt in item.get("positivePrompts") or []:
            label = f"{timestamp} / {Path(workflow_id).stem or 'workflow'} / Segment {prompt.get('index', 1)}"
            add_option("positive", prompt.get("text"), label, "history", workflow_id, prompt.get("index"))
        for prompt in item.get("negativePrompts") or []:
            label = f"{timestamp} / {Path(workflow_id).stem or 'workflow'} / Segment {prompt.get('index', 1)}"
            add_option("negative", prompt.get("text"), label, "history", workflow_id, prompt.get("index"))

    for item in configs:
        snapshot = item.get("snapshot") or {}
        workflow_id = snapshot.get("workflowId") or item.get("workflowId") or ""
        timestamp = item.get("timestamp") or "-"
        for segment in snapshot.get("segments") or []:
            label = f"{timestamp} / {Path(workflow_id).stem or 'workflow'} / Segment {segment.get('index', 1)}"
            add_option("positive", segment.get("positivePrompt"), label, "config", workflow_id, segment.get("index"))
            add_option("negative", segment.get("negativePromptAddition") or segment.get("negativePrompt"), label, "config", workflow_id, segment.get("index"))

    return {
        "positive": options["positive"][:100],
        "negative": options["negative"][:100],
    }


def create_upload(payload: dict) -> dict:
    with studio_repository() as repository:
        return repository.create_upload(payload)


def get_asset(asset_id: str) -> tuple[dict, Path]:
    with studio_repository() as repository:
        return repository.get_asset(asset_id)


def register_asset(file_path: Path, asset_type: str, mime_type: str | None = None, file_name: str | None = None) -> dict:
    with studio_repository() as repository:
        return repository.register_asset(Path(file_path), asset_type, mime_type, file_name)


def hydrate_input_images(item: dict) -> list[dict]:
    with studio_repository() as repository:
        return repository.hydrate_input_images(item)


def asset_to_runpod_image(asset_id: str, fallback_name: str | None = None) -> dict:
    asset, path = get_asset(asset_id)
    return {
        "name": safe_filename(asset.get("fileName") or fallback_name or path.name),
        "path": str(path),
    }


def build_runpod_images(payload: dict) -> list[dict]:
    images = []
    keyframes = sorted(
        (keyframe for keyframe in payload.get("keyframes") or [] if isinstance(keyframe, dict)),
        key=lambda keyframe: int(keyframe.get("index") or 0),
    )
    for keyframe in keyframes:
        upload_id = keyframe.get("uploadId")
        if not upload_id:
            continue
        images.append(asset_to_runpod_image(upload_id, keyframe.get("fileName")))
    return images


def build_runpod_payload(workflow: dict, images: list[dict]) -> dict:
    input_body = {"workflow": workflow}
    if images:
        input_body["images"] = [
            {"name": image["name"], "image": encode_file_base64(Path(image["path"]))}
            for image in images
        ]
    return {"input": input_body}


def existing_save_video_outputs(workflow: dict, workflow_id: str, segments: list[dict]) -> dict:
    return output_service.existing_save_video_outputs(workflow, workflow_id, segments, get_settings().workflows_dir)


def prepare_workflow_for_job(payload: dict) -> tuple[dict, list[dict], dict]:
    return workflow_patch_service.prepare_workflow_for_job(
        payload,
        get_settings().workflows_dir,
        build_runpod_images,
        existing_save_video_outputs,
    )


def runpod_request(method: str, path: str, payload=None):
    settings = get_settings()
    return runpod_client_request(
        method,
        path,
        api_key=settings.runpod_api_key,
        endpoint_id=settings.runpod_endpoint_id,
        base_url=settings.runpod_base_url,
        timeout=settings.runpod_timeout,
        payload=payload,
    )


def runpod_connection() -> dict:
    settings = get_settings()
    return runpod_connection_status(
        api_key=settings.runpod_api_key,
        endpoint_id=settings.runpod_endpoint_id,
        base_url=settings.runpod_base_url,
        timeout=settings.runpod_timeout,
    )


def save_runpod_outputs(result: dict, job: dict) -> dict:
    return output_service.save_runpod_outputs(result, job, data_paths()["outputs"], register_asset)


def build_wan_node_config_snapshot(workflow_id: str, segments_payload: list[dict]) -> dict:
    return workflow_patch_service.build_wan_node_config_snapshot(workflow_id, segments_payload, get_settings().workflows_dir)


def job_runtime() -> job_service.JobRuntime:
    return job_service.JobRuntime(
        jobs=JOBS,
        dry_run=get_settings().dry_run,
        prepare_workflow_for_job=prepare_workflow_for_job,
        build_runpod_payload=build_runpod_payload,
        runpod_request=runpod_request,
        save_runpod_outputs=save_runpod_outputs,
        append_history=append_history,
        build_wan_node_config_snapshot=build_wan_node_config_snapshot,
        hydrate_input_images=hydrate_input_images,
        record_job=lambda job: record_job_status(job, resolve_asset=get_asset),
    )


def create_job(payload: dict, *, user: dict[str, object]) -> dict:
    """Submit one task after enforcing the persisted active-task policy.

    The browser payload is intentionally not trusted for task ownership.  The
    authenticated request principal is copied into the immutable task snapshot
    immediately before the RunPod request is made.
    """
    user_id = str(user.get("id") or "").strip()
    if not user_id:
        raise ValueError("인증된 사용자 정보를 찾을 수 없습니다.")
    with JOB_LOCK:
        session = SessionLocal()
        try:
            assert_task_submission_allowed(session, user_id)
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

        safe_payload = dict(payload)
        safe_payload["user"] = {
            "id": user_id,
            "name": str(user.get("name") or user_id),
            "role": str(user.get("role") or ""),
            "permissions": list(user.get("permissions") or []),
        }
        return job_service.create_job(job_runtime(), safe_payload)


def job_status(task_id: str) -> dict:
    with JOB_LOCK:
        if task_id not in JOBS:
            restored = restore_job_from_task(task_id)
            if restored:
                JOBS[task_id] = restored
        return job_service.job_status(job_runtime(), task_id)


def cancel_job(task_id: str) -> dict:
    with JOB_LOCK:
        if task_id not in JOBS:
            restored = restore_job_from_task(task_id)
            if restored:
                JOBS[task_id] = restored
        return job_service.cancel_job(job_runtime(), task_id)


def monitor_active_jobs() -> dict:
    """Poll persisted active tasks so status survives browser/session loss.

    A failed RunPod status lookup is isolated to the affected task.  The next
    monitor cycle retries it rather than changing a task to failed merely
    because the status API had a transient error.
    """
    task_ids = active_task_ids()
    failures: list[str] = []
    for task_id in task_ids:
        try:
            job_status(task_id)
        except Exception:
            failures.append(task_id)
    return {"checked": len(task_ids), "failures": failures}


def job_prompts(task_id: str) -> list[dict]:
    return task_prompts(task_id)


def update_job_prompt_quality(task_id: str, segment_index: int, payload: dict) -> dict:
    return update_task_prompt_quality(task_id, segment_index, payload)


def update_job_prompt_review(task_id: str, segment_index: int, payload: dict) -> dict:
    return update_task_prompt_review(task_id, segment_index, payload)


def reusable_prompts(
    *,
    keyword: str = "",
    workflow_id: str = "",
    min_rating: int | None = None,
    reviewed_only: bool = False,
    reuse_eligible: bool | None = None,
    page: int = 1,
    page_size: int = 20,
) -> dict:
    return reusable_task_prompts(
        keyword=keyword,
        workflow_id=workflow_id,
        min_rating=min_rating,
        reviewed_only=reviewed_only,
        reuse_eligible=reuse_eligible,
        page=page,
        page_size=page_size,
    )


def report_markdown(payload: dict) -> str:
    item = payload.get("historyItem") or payload.get("snapshot") or {}
    segments = item.get("segments") if isinstance(item.get("segments"), list) else []
    config = item.get("configJson") or item.get("config") or {}
    wan_node_config = item.get("wanNodeConfig") or {}
    if segments:
        config = segments[0].get("config") or config

    lines = [
        "# DOBEDUB STUDIO 작업 리포트",
        "",
        f"- 생성일시: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"- Task ID: {item.get('taskId', '-')}",
        f"- Workflow: {item.get('workflowId') or item.get('workflow') or item.get('workflowName') or '-'}",
        f"- Status: {item.get('status', '-')}",
        f"- FPS: {config.get('fps') or item.get('fps') or '-'}",
        f"- Applied Seed: {item.get('generationSeed') or config.get('seed') or item.get('seed') or '-'}",
        f"- Segments: {item.get('segmentCount') or len(segments) or item.get('segments') or '-'}",
        "",
        "## Prompt",
        "",
        item.get("positivePrompt") or item.get("prompt") or "-",
        "",
        "## Negative Prompt",
        "",
        item.get("negativePrompt") or "-",
        "",
        "## Node Config",
        "",
        "```json",
        json.dumps(wan_node_config or config, ensure_ascii=False, indent=2),
        "```",
    ]
    return "\n".join(lines) + "\n"


def create_report(payload: dict) -> dict:
    report_id = f"report_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
    markdown = report_markdown(payload)
    reports_dir = data_paths()["reports"]
    reports_dir.mkdir(parents=True, exist_ok=True)
    path = reports_dir / f"{report_id}.md"
    path.write_text(markdown, encoding="utf-8")
    return {
        "reportId": report_id,
        "downloadUrl": f"/api/reports/{report_id}",
        "markdown": markdown,
    }


def report_path(report_id: str) -> Path:
    path = data_paths()["reports"] / f"{Path(report_id).name}.md"
    if not path.exists():
        raise FileNotFoundError(report_id)
    return path
