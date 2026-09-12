from __future__ import annotations

from sqlalchemy.orm import Session

from backend.app.core.timezone_utils import UTC_TIMEZONE, timestamp_fields, utc_now
from backend.app.db.models import SandboxPodSetting


def sandbox_pod_settings(session: Session) -> SandboxPodSetting:
    """Return the singleton settings row, creating it with defaults on first use."""
    row = session.get(SandboxPodSetting, 1)
    if row:
        return row
    row = SandboxPodSetting(id=1, selected_pod_id=None, auto_switch_on_start_failure=True, pod_priority_json=[], replace_same_gpu_pods=True)
    session.add(row)
    session.flush()
    return row


def sandbox_pod_settings_payload(session: Session) -> dict:
    row = sandbox_pod_settings(session)
    return {
        "selectedPodId": row.selected_pod_id or None,
        "autoSwitchOnStartFailure": bool(row.auto_switch_on_start_failure),
        "podPriority": _priority_list(row.pod_priority_json),
        "replaceSameGpuPods": bool(row.replace_same_gpu_pods) if row.replace_same_gpu_pods is not None else True,
        "updatedBy": row.updated_by,
        **timestamp_fields(
            "updatedAt", row.updated_at, naive_timezone=UTC_TIMEZONE, source_timezone="UTC", source="sandbox-pod-settings"
        ),
    }


def select_sandbox_pod(session: Session, *, pod_id: str | None, updated_by: str | None) -> dict:
    normalized = str(pod_id or "").strip() or None
    row = sandbox_pod_settings(session)
    row.selected_pod_id = normalized
    row.updated_by = updated_by
    row.updated_at = utc_now().replace(tzinfo=None)
    session.commit()
    return sandbox_pod_settings_payload(session)


def update_sandbox_pod_settings(
    session: Session,
    *,
    auto_switch_on_start_failure: object,
    pod_priority: object,
    updated_by: str | None,
    replace_same_gpu_pods: object = True,
) -> dict:
    if not isinstance(auto_switch_on_start_failure, bool):
        raise ValueError("autoSwitchOnStartFailure는 true/false여야 합니다.")
    if not isinstance(replace_same_gpu_pods, bool):
        raise ValueError("replaceSameGpuPods는 true/false여야 합니다.")
    if not isinstance(pod_priority, list) or any(not isinstance(item, str) for item in pod_priority):
        raise ValueError("podPriority는 Pod ID 문자열 목록이어야 합니다.")
    ordered: list[str] = []
    for item in pod_priority:
        value = item.strip()
        if value and value not in ordered:
            ordered.append(value)
    row = sandbox_pod_settings(session)
    row.auto_switch_on_start_failure = auto_switch_on_start_failure
    row.pod_priority_json = ordered
    row.replace_same_gpu_pods = replace_same_gpu_pods
    row.updated_by = updated_by
    row.updated_at = utc_now().replace(tzinfo=None)
    session.commit()
    return sandbox_pod_settings_payload(session)


def _priority_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item).strip()]
