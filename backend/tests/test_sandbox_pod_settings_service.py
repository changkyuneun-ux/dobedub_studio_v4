from __future__ import annotations

import pytest

from backend.app.services.sandbox_pod_settings_service import (
    sandbox_pod_settings_payload,
    select_sandbox_pod,
    update_sandbox_pod_settings,
)


def test_settings_row_is_created_with_defaults(db_session):
    payload = sandbox_pod_settings_payload(db_session)

    assert payload["selectedPodId"] is None
    assert payload["autoSwitchOnStartFailure"] is True
    assert payload["podPriority"] == []
    assert payload["replaceSameGpuPods"] is True


def test_select_and_update_persist(db_session):
    select_sandbox_pod(db_session, pod_id="caiuvooekq9qqw", updated_by=None)
    update_sandbox_pod_settings(
        db_session,
        auto_switch_on_start_failure=False,
        pod_priority=["3i50u1x4pyz0vr", "caiuvooekq9qqw", "3i50u1x4pyz0vr", " "],
        updated_by=None,
    )

    payload = sandbox_pod_settings_payload(db_session)

    assert payload["selectedPodId"] == "caiuvooekq9qqw"
    assert payload["autoSwitchOnStartFailure"] is False
    assert payload["podPriority"] == ["3i50u1x4pyz0vr", "caiuvooekq9qqw"]


def test_update_rejects_invalid_payloads(db_session):
    with pytest.raises(ValueError):
        update_sandbox_pod_settings(db_session, auto_switch_on_start_failure=True, pod_priority="x", updated_by=None)
    with pytest.raises(ValueError):
        update_sandbox_pod_settings(db_session, auto_switch_on_start_failure="yes", pod_priority=[], updated_by=None)
