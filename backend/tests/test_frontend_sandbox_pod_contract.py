from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCREEN = (ROOT / "frontend" / "src" / "screens" / "adminScreens.tsx").read_text(encoding="utf-8")
CLIENT = (ROOT / "frontend" / "src" / "api" / "client.ts").read_text(encoding="utf-8")
STYLES = (ROOT / "frontend" / "src" / "styles.css").read_text(encoding="utf-8")


def _sandbox_component() -> str:
    return SCREEN.split("export function Create5bScreen", 1)[1].split("export function TaskPolicyScreen", 1)[0]


def _sandbox_section() -> str:
    return _sandbox_component().split('activeItem="adminSandbox"', 1)[1].split("</AppShell>", 1)[0]


def test_client_exposes_multi_pod_api_and_structured_errors():
    assert "export class ApiError extends Error" in CLIENT
    assert "export type SandboxPodAttempt" in CLIENT
    assert "export type SandboxPodSummary" in CLIENT
    assert "export type SandboxPodStartFailure" in CLIENT
    assert 'gpuTier?: "primary" | "fallback" | "unknown"' in CLIENT
    assert "authRequired?: boolean" in CLIENT
    assert "selectSandboxPod: (podId: string)" in CLIENT
    assert "updateSandboxPodSettings:" in CLIENT
    assert '"/api/admin/sandbox-pod/select"' in CLIENT
    assert '"/api/admin/sandbox-pod/settings"' in CLIENT
    # Structured 409/503 detail objects keep their message and payload.
    assert "throw new ApiError(message, response.status, detail)" in CLIENT


def test_panel_renders_pod_table_with_radio_selection_and_switch_label():
    section = _sandbox_section()
    assert "v3-sandbox-pod-table" in section
    assert 'type="radio"' in section
    assert 'name="sandbox-pod-select"' in section
    assert "selectSandboxPod" in _sandbox_component()
    assert '"전환 후 시작"' in _sandbox_component()
    assert "진행 중인 ComfyUI 작업은 중단됩니다" in section


def test_panel_keeps_last_known_status_on_start_failure():
    component = _sandbox_component()
    control = component.split("async function controlSandboxPod", 1)[1].split("async function saveSettings", 1)[0]
    catch_block = control.split("} catch (error) {", 1)[1]
    assert "setSandboxPod(null)" not in control
    assert "setSandboxPod(" not in catch_block
    assert "setStartFailure(detail)" in catch_block
    assert "retryAfterSeconds" in catch_block


def test_panel_renders_conflict_banner_attempts_badges_and_countdown():
    section = _sandbox_section()
    assert "볼륨 손상 위험" in section
    assert "선택 파드만 남기고 정지" in section
    assert "<SandboxAttemptsStrip" in section
    assert 'gpuTier === "fallback"' in section
    assert "service.authRequired" in section
    assert "retryCountdown" in section
    assert "CONFLICT" in section


def test_panel_has_auto_switch_settings_with_priority_controls():
    section = _sandbox_section()
    assert "선택 파드 기동 실패 시 다른 파드 자동 시작" in section
    assert "updateSandboxPodSettings" in _sandbox_component()
    assert "movePriority(podId, -1)" in section
    assert "movePriority(podId, 1)" in section


def test_panel_uses_runpod_pod_name_first_and_id_second():
    component = _sandbox_component()
    section = _sandbox_section()
    assert "function sandboxPodDisplay" in SCREEN
    assert "<strong>{sandboxPodName(pod)}</strong>" in section
    assert "sandboxPodDisplay(selectedPod)" in section
    assert "selectedPodMissing" in component
    assert "같은 이름의 파드를 다시 선택하세요" in section
    assert "podName?: string | null" in CLIENT


def test_panel_supports_replace_policy_and_manual_terminate():
    section = _sandbox_section()
    assert "새 파드 생성 시 같은 GPU의 정지 파드 삭제" in section
    assert "terminateSandboxPod" in CLIENT and "replaceSameGpuPods?: boolean" in CLIENT
    assert 'kind: "terminate"' in _sandbox_component()
    assert "v3-sandbox-pod-terminate" in section
    assert "되돌릴 수 없습니다" in section


def test_styles_define_sandbox_multi_pod_classes():
    for class_name in (".v3-sandbox-pod-row", ".v3-sandbox-attempt.is-fail", ".v3-sandbox-banner.is-danger", ".v3-sandbox-priority-row", ".v3-sandbox-columns"):
        assert class_name in STYLES
