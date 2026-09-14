from __future__ import annotations

import unittest
from unittest.mock import patch

from backend.app.core.config import Settings
from backend.app.services.sandbox_pod_service import (
    _gpu_type_name,
    _hydrate_pod,
    _hydrate_pod_if_needed,
    _lifecycle_event_timestamp,
    _present_pod,
    _request,
    _resolve_pod,
    _runtime_metrics,
)
from backend.app.core.timezone_utils import UTC_TIMEZONE


class SandboxPodLifecycleTimestampTests(unittest.TestCase):
    @patch("backend.app.services.sandbox_pod_service.urllib.request.urlopen")
    def test_runpod_rest_request_uses_explicit_http_client_headers(self, urlopen: object) -> None:
        captured = {}

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_: object) -> None:
                return None

            def read(self) -> bytes:
                return b"{}"

        def fake_urlopen(request: object, timeout: int) -> Response:
            captured["headers"] = dict(request.header_items())
            captured["timeout"] = timeout
            return Response()

        urlopen.side_effect = fake_urlopen

        _request(Settings(sandbox_pod_api_key="test-key", sandbox_pod_timeout=7), "GET", "/pods")

        self.assertEqual(captured["timeout"], 7)
        self.assertEqual(captured["headers"]["Authorization"], "Bearer test-key")
        self.assertEqual(captured["headers"]["User-agent"], "dobedub-studio/1.0")
        self.assertEqual(captured["headers"]["Accept"], "application/json")

    def test_extracts_runpod_lifecycle_event_timestamp(self) -> None:
        value = "Rented by User: Fri Aug 07 2026 07:51:24 GMT+0000 (Coordinated Universal Time)"

        parsed = _lifecycle_event_timestamp(value)

        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.tzinfo, UTC_TIMEZONE)
        self.assertEqual(parsed.strftime("%Y-%m-%dT%H:%M:%SZ"), "2026-08-07T07:51:24Z")

    def test_keeps_unparseable_event_without_inventing_a_time(self) -> None:
        self.assertIsNone(_lifecycle_event_timestamp("Provisioning requested by provider"))

    @patch("backend.app.services.sandbox_pod_service._request")
    def test_returns_runtime_metrics_without_exposing_provider_response_shape(self, request: object) -> None:
        request.return_value = {
            "id": "pod-123",
            "status": "RUNNING",
            "runtime": {
                "uptime": 3661,
                "cpu": {"util": 12.8},
                "memory": {"util": 34.2},
                "gpus": [{"id": "gpu-0", "util": 45.5, "memoryUtil": 67.1}],
            },
        }

        result = _runtime_metrics(
            Settings(sandbox_pod_api_key="test-key"),
            "pod-123",
            {"containerDiskInGb": 150, "volumeInGb": 1000, "networkVolumeId": "volume-1"},
        )

        self.assertTrue(result["available"])
        self.assertEqual(result["uptimeSeconds"], 3661)
        self.assertEqual(result["cpuPercent"], 12.8)
        self.assertEqual(result["gpus"][0]["memoryUtilPercent"], 67.1)
        self.assertEqual(result["storage"]["networkVolumeId"], "volume-1")
        self.assertEqual(request.call_args.kwargs.get("base_url"), "https://api.runpod.io/v2")
        self.assertEqual(request.call_args.args[2], "/pods/pod-123")

    @patch("backend.app.services.sandbox_pod_service._request")
    def test_hydrate_pod_reads_detail_from_rest_v2_not_v1(self, request: object) -> None:
        # 2026-09-14: RunPod's v1 GET /pods/{id} does not carry GPU identification
        # (no gpuTypeId/gpu.id) — only REST v2's pod detail does (confirmed against
        # RunPod's own docs: docs.runpod.io/api-reference-v2/pods/get-a-pod). This
        # call used to omit base_url (defaulting to v1), so a pod whose /pods LIST
        # entry lacked GPU info never got it filled in, leaving VRAM/재고 blank in
        # the admin screen even after the catalog/runtime-metrics host was fixed.
        request.return_value = {"gpu": {"id": "NVIDIA GeForce RTX 5090"}, "memoryInGb": 60}

        result = _hydrate_pod(Settings(sandbox_pod_api_key="test-key"), {"id": "pod-123"}, strict=False)

        self.assertEqual(request.call_args.kwargs.get("base_url"), "https://api.runpod.io/v2")
        self.assertEqual(request.call_args.args[2], "/pods/pod-123")
        self.assertEqual(_gpu_type_name(result), "NVIDIA GeForce RTX 5090")

    @patch("backend.app.services.sandbox_pod_service._request")
    def test_hydrate_pod_if_needed_fills_in_gpu_missing_from_the_list_response(self, request: object) -> None:
        # Mirrors a real RunPod v1 /pods LIST entry: ports/memoryInGb/costPerHr
        # present but no gpu type field at all (as reproduced against a live pod).
        list_pod = {"id": "pod-123", "ports": ["8188/http"], "memoryInGb": 60, "costPerHr": 0.99}
        request.return_value = {"gpu": {"id": "NVIDIA GeForce RTX 5090"}}

        result = _hydrate_pod_if_needed(Settings(sandbox_pod_api_key="test-key"), list_pod)

        self.assertEqual(request.call_args.kwargs.get("base_url"), "https://api.runpod.io/v2")
        self.assertEqual(_gpu_type_name(result), "NVIDIA GeForce RTX 5090")

    @patch("backend.app.services.sandbox_pod_service._runtime_metrics", return_value={"available": True, "gpus": []})
    @patch("backend.app.services.sandbox_pod_service._runtime_status", return_value="READY")
    def test_presents_provider_times_and_lifecycle_event_separately(self, _: object, __: object) -> None:
        result = _present_pod(
            object(),
            {
                "id": "pod-123",
                "name": "sandbox",
                "desiredStatus": "RUNNING",
                "ports": ["8188/http", "8080/http", "8888/http", "22/tcp"],
                "lastStartedAt": "2026-08-07T07:51:24Z",
                "lastStatusChange": "Rented by User: Fri Aug 07 2026 07:51:24 GMT+0000 (Coordinated Universal Time)",
            },
            "template-id",
        )

        self.assertEqual(result["lastStartedAtUtc"], "2026-08-07T07:51:24Z")
        self.assertEqual(result["lastStartedAtKst"], "2026-08-07 16:51:24 KST")
        self.assertEqual(result["lastStatusChangeUtc"], "2026-08-07T07:51:24Z")
        self.assertEqual(result["lastLifecycleEvent"], "Rented by User: Fri Aug 07 2026 07:51:24 GMT+0000 (Coordinated Universal Time)")
        self.assertIsNotNone(result["checkedAtUtc"])
        self.assertEqual(result["httpServices"], [
            {"internalPort": 8188, "url": "https://pod-123-8188.proxy.runpod.net", "label": "ComfyUI"},
            {"internalPort": 8080, "url": "https://pod-123-8080.proxy.runpod.net", "label": "FileBrowser"},
            {"internalPort": 8888, "url": "https://pod-123-8888.proxy.runpod.net", "label": "JupyterLab"},
        ])


class SandboxPodResolutionTests(unittest.TestCase):
    """The Network Volume is the Pod's identity; the template only describes how to build a new one."""

    VOLUME = "18jhx6rxjd"
    TEMPLATE = "nh1d177m2w"

    def setUp(self) -> None:
        # 2026-09-13 성능: _resolve_pods()의 짧은 TTL 목록 캐시가 이전 테스트의 응답을
        # 들고 넘어오지 않도록 매 테스트 시작 전 비운다.
        service._pods_list_cache["at"] = 0.0
        service._pods_list_cache["value"] = None
        service._pods_list_cache["volumeId"] = None

    def _settings(self) -> Settings:
        return Settings(
            sandbox_pod_api_key="test-key",
            sandbox_pod_network_volume_id=self.VOLUME,
            sandbox_pod_template_id=self.TEMPLATE,
        )

    def _pods(self) -> list[dict]:
        return [
            {
                "id": "caiuvooekq9qqw",
                "name": "dobedub_comfyUI_Sandbox2",
                "desiredStatus": "EXITED",
                "templateId": self.TEMPLATE,
                "networkVolume": {"id": self.VOLUME},
                "lastStartedAt": "2026-09-11T00:24:21Z",
            },
            {
                # Created via the console / REST v2: same volume, no template link.
                "id": "3i50u1x4pyz0vr",
                "name": "dobedub_comfyUI_Sandbox2",
                "desiredStatus": "RUNNING",
                "templateId": None,
                "networkVolume": {"id": self.VOLUME},
                "lastStartedAt": "2026-09-11T08:23:11Z",
            },
            {
                # Same template on a different volume must never be selected.
                "id": "otherpod000000",
                "name": "unrelated",
                "desiredStatus": "RUNNING",
                "templateId": self.TEMPLATE,
                "networkVolume": {"id": "zzz"},
            },
        ]

    @patch("backend.app.services.sandbox_pod_service._request")
    def test_volume_selector_ignores_template_filter_and_picks_running_pod(self, request: object) -> None:
        pods = self._pods()

        def fake_request(settings, method, path, body=None, **kwargs):
            if path.startswith("/pods?"):
                return pods
            pod_id = path.rsplit("/", 1)[-1]
            return next(pod for pod in pods if pod["id"] == pod_id)

        request.side_effect = fake_request

        pod, resolved_by = _resolve_pod(self._settings())

        self.assertEqual(pod["id"], "3i50u1x4pyz0vr")
        self.assertEqual(resolved_by, "network-volume")

    @patch("backend.app.services.sandbox_pod_service._request")
    def test_template_filter_still_applies_when_only_template_is_configured(self, request: object) -> None:
        pods = self._pods()

        def fake_request(settings, method, path, body=None, **kwargs):
            if path.startswith("/pods?"):
                return pods
            pod_id = path.rsplit("/", 1)[-1]
            return next(pod for pod in pods if pod["id"] == pod_id)

        request.side_effect = fake_request
        settings = Settings(sandbox_pod_api_key="test-key", sandbox_pod_template_id=self.TEMPLATE)

        pod, resolved_by = _resolve_pod(settings)

        self.assertEqual(pod["id"], "otherpod000000")
        self.assertEqual(resolved_by, "template-id")

    @patch("backend.app.services.sandbox_pod_service._request")
    def test_all_exited_pods_select_most_recent(self, request: object) -> None:
        pods = self._pods()
        pods[1]["desiredStatus"] = "EXITED"

        def fake_request(settings, method, path, body=None, **kwargs):
            if path.startswith("/pods?"):
                return pods
            pod_id = path.rsplit("/", 1)[-1]
            return next(pod for pod in pods if pod["id"] == pod_id)

        request.side_effect = fake_request

        pod, _ = _resolve_pod(self._settings())

        self.assertEqual(pod["id"], "3i50u1x4pyz0vr")


if __name__ == "__main__":
    unittest.main()


# ---------------------------------------------------------------------------
# Multi-pod selection, single-running invariant and GPU fallback (spec 2026-09-11)
# ---------------------------------------------------------------------------

import json  # noqa: E402
import urllib.error  # noqa: E402
from io import BytesIO  # noqa: E402

from backend.app.services import sandbox_pod_service as service  # noqa: E402
from backend.app.services.sandbox_pod_service import (  # noqa: E402
    SandboxPodApiError,
    SandboxPodConflict,
    SandboxPodPrefs,
    SandboxPodUnavailable,
    _classify_error,
    _gpu_candidates,
    sandbox_pod_live,
    sandbox_pod_status,
    start_sandbox_pod,
    stop_sandbox_pod,
    terminate_sandbox_pod,
)

VOLUME = "18jhx6rxjd"
TEMPLATE = "nh1d177m2w"
GPU_5090 = "NVIDIA GeForce RTX 5090"
GPU_PRO6000 = "NVIDIA RTX PRO 6000 Blackwell Workstation Edition"
GPU_PRO4500 = "NVIDIA RTX PRO 4500 Blackwell"
NO_CAP = '{"error":"create pod: There are no instances currently available","status":500}'


def _pod_5090(status: str = "EXITED") -> dict:
    return {
        "id": "caiuvooekq9qqw", "name": "dobedub_comfyUI_Sandbox_RTX 5090", "desiredStatus": status,
        "templateId": TEMPLATE, "networkVolume": {"id": VOLUME}, "gpuTypeIds": [GPU_5090],
        "costPerHr": 0.99, "memoryInGb": 60, "ports": ["8188/http", "8888/http"],
        "lastStartedAt": "2026-09-11T08:13:54Z",
    }


def _pod_pro6000(status: str = "RUNNING") -> dict:
    return {
        "id": "3i50u1x4pyz0vr", "name": "dobedub_comfyUI_Sandbox_RTX PRO 6000", "desiredStatus": status,
        "templateId": None, "networkVolume": {"id": VOLUME}, "gpuTypeIds": [GPU_PRO6000],
        "costPerHr": 2.19, "memoryInGb": 262, "ports": ["8188/http", "8888/http"],
        "env": [{"key": "JUPYTER_PASSWORD", "value": "x"}],
        "lastStartedAt": "2026-09-11T08:23:11Z", "runtime": {"uptimeInSeconds": 10},
    }


class _FakeResponse:
    def __init__(self, body: object) -> None:
        self._body = json.dumps(body).encode("utf-8")
        self.status = 200

    def __enter__(self):
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def read(self) -> bytes:
        return self._body


def _http_error(code: int, body: str) -> urllib.error.HTTPError:
    return urllib.error.HTTPError("https://rest.runpod.io/v1", code, "err", hdrs=None, fp=BytesIO(body.encode("utf-8")))


class _RunPodScript:
    """Scripted urlopen: (METHOD, path) → queue of bodies / exceptions.

    GET /pods/{id} falls back to the live ``pods`` dict so hydration works
    without scripting every detail call.
    """

    def __init__(self, pods: list[dict], script: dict[tuple[str, str], list] | None = None) -> None:
        self.pods = {pod["id"]: pod for pod in pods}
        self.script = {key: list(value) for key, value in (script or {}).items()}
        self.calls: list[tuple[str, str, dict | None]] = []

    def __call__(self, request, timeout):
        # 2026-09-14: _hydrate_pod's detail fetch now targets REST v2 (api.runpod.io)
        # for GPU info, while everything else still uses v1 (rest.runpod.io) — strip
        # whichever host prefix is present so this fake serves both transparently.
        path = request.full_url.replace("https://rest.runpod.io/v1", "").replace("https://api.runpod.io/v2", "")
        method = request.get_method()
        body = json.loads(request.data) if request.data else None
        self.calls.append((method, path, body))
        key = (method, path.split("?")[0])
        queue = self.script.get(key)
        if queue:
            item = queue.pop(0)
            if isinstance(item, Exception):
                raise item
            if callable(item):
                item = item()
            return _FakeResponse(item)
        if key == ("GET", "/pods"):
            return _FakeResponse(list(self.pods.values()))
        if method == "GET" and path.startswith("/pods/"):
            pod_id = path.rsplit("/", 1)[-1]
            if pod_id in self.pods:
                return _FakeResponse(self.pods[pod_id])
            raise _http_error(404, "pod not found")
        if method == "POST" and path.endswith("/stop"):
            pod_id = path.split("/")[2]
            self.pods[pod_id]["desiredStatus"] = "EXITED"
            self.pods[pod_id].pop("runtime", None)
            return _FakeResponse({"id": pod_id, "desiredStatus": "EXITED"})
        if method == "POST" and path.endswith("/start"):
            pod_id = path.split("/")[2]
            self.pods[pod_id]["desiredStatus"] = "RUNNING"
            self.pods[pod_id]["runtime"] = {"uptimeInSeconds": 1}
            return _FakeResponse({"id": pod_id, "desiredStatus": "RUNNING"})
        if method == "DELETE" and path.startswith("/pods/"):
            pod_id = path.rsplit("/", 1)[-1]
            self.pods.pop(pod_id, None)
            return _FakeResponse({})
        raise AssertionError(f"unexpected call {method} {path}")

    def posts(self, suffix: str) -> list[tuple[str, dict | None]]:
        return [(path, body) for method, path, body in self.calls if method == "POST" and path.endswith(suffix)]

    def deletes(self) -> list[str]:
        return [path for method, path, _ in self.calls if method == "DELETE"]


def _settings(**overrides) -> Settings:
    base = dict(
        sandbox_pod_api_key="k",
        sandbox_pod_network_volume_id=VOLUME,
        sandbox_pod_template_id=TEMPLATE,
        sandbox_pod_gpu_type_id=GPU_5090,
        sandbox_pod_gpu_fallback_type_ids=(GPU_PRO4500, GPU_PRO6000),
        sandbox_pod_create_attempt_delay_seconds=0,
        sandbox_pod_stop_wait_seconds=6,
    )
    base.update(overrides)
    return Settings(**base)


class SandboxPodMultiPodTests(unittest.TestCase):
    def setUp(self) -> None:
        # 2026-09-13 성능: _resolve_pods()의 짧은 TTL 목록 캐시가 이전 테스트의 응답을
        # 들고 넘어오지 않도록 매 테스트 시작 전 비운다.
        service._pods_list_cache["at"] = 0.0
        service._pods_list_cache["value"] = None
        service._pods_list_cache["volumeId"] = None

    def _patches(self, fake, catalog=None):
        return [
            patch("backend.app.services.sandbox_pod_service.urllib.request.urlopen", side_effect=fake),
            patch("backend.app.services.sandbox_pod_service._runtime_status", return_value="INITIALIZING"),
            patch("backend.app.services.sandbox_pod_service._runtime_metrics", return_value={"available": False, "mode": "configuration", "gpus": []}),
            patch("backend.app.services.sandbox_pod_service._sleep"),
            patch("backend.app.services.sandbox_pod_service._fetch_gpu_catalog", return_value=catalog),
        ]

    def _run(self, fn, fake, *args, catalog=None, **kwargs):
        patches = self._patches(fake, catalog)
        for item in patches:
            item.start()
        try:
            return fn(*args, **kwargs)
        finally:
            for item in patches:
                item.stop()

    # --- helpers -----------------------------------------------------------

    def test_classify_error(self) -> None:
        self.assertEqual(_classify_error(SandboxPodApiError(500, NO_CAP)), "no_capacity")
        self.assertEqual(_classify_error(SandboxPodApiError(503, "")), "no_capacity")
        self.assertEqual(_classify_error(SandboxPodApiError(404, "pod not found")), "not_found")
        for code in (400, 401, 403, 422):
            self.assertEqual(_classify_error(SandboxPodApiError(code, "bad")), "config")
        self.assertEqual(_classify_error(SandboxPodApiError(None, "timed out")), "transient")

    def test_gpu_candidates_keep_priority_dedupe_and_skip_low_vram(self) -> None:
        settings = _settings(sandbox_pod_gpu_fallback_type_ids=("NVIDIA RTX A4000", GPU_5090, GPU_PRO6000))
        self.assertEqual(_gpu_candidates(settings, None), [(GPU_5090, None), ("NVIDIA RTX A4000", None), (GPU_PRO6000, None)])
        vram = {GPU_5090: 32, "NVIDIA RTX A4000": 16, GPU_PRO6000: 96}
        self.assertEqual(_gpu_candidates(settings, vram), [(GPU_5090, None), ("NVIDIA RTX A4000", "vram"), (GPU_PRO6000, None)])
        self.assertEqual(_gpu_candidates(_settings(sandbox_pod_gpu_fallback_type_ids=()), None), [(GPU_5090, None)])

    # --- status --------------------------------------------------------------

    def test_1_status_lists_every_pod_on_volume_and_fills_legacy_fields_from_active(self) -> None:
        other_volume = {**_pod_5090("RUNNING"), "id": "otherpod000000", "networkVolume": {"id": "zzz"}}
        fake = _RunPodScript([_pod_5090(), _pod_pro6000(), other_volume])

        result = self._run(sandbox_pod_status, fake, _settings(), prefs=SandboxPodPrefs(selected_pod_id="caiuvooekq9qqw"))

        self.assertEqual([pod["podId"] for pod in result["pods"]], ["caiuvooekq9qqw", "3i50u1x4pyz0vr"])
        self.assertEqual(result["activePodId"], "3i50u1x4pyz0vr")
        self.assertEqual(result["selectedPodId"], "caiuvooekq9qqw")
        self.assertFalse(result["conflict"])
        self.assertEqual(result["podId"], "3i50u1x4pyz0vr")
        self.assertEqual(result["resolvedBy"], "network-volume")
        self.assertEqual(result["gpuTier"], "fallback")
        jupyter = next(s for s in result["httpServices"] if s["internalPort"] == 8888)
        self.assertTrue(jupyter["authRequired"])
        self.assertEqual(result["pods"][0]["gpuTier"], "primary")
        self.assertEqual(result["pods"][1]["pricePerHr"], 2.19)
        self.assertEqual(result["attempts"], [])

    def test_status_pod_list_carries_catalog_stock_level(self) -> None:
        # 2026-09-13: sandbox pod 목록에서 재고(gpuStockLevel)를 표시하는 요구사항.
        # 카탈로그에 재고가 있으면 그대로, 없으면(캐시 미조회 등) None으로 노출한다.
        fake = _RunPodScript([_pod_5090(), _pod_pro6000()])
        catalog = {
            GPU_5090: {"memoryInGb": 32, "securePrice": 0.99, "displayName": "RTX 5090", "stockLevel": "MEDIUM"},
            GPU_PRO6000: {"memoryInGb": 96, "securePrice": 2.19, "displayName": "RTX PRO 6000", "stockLevel": "HIGH"},
        }

        result = self._run(sandbox_pod_status, fake, _settings(), prefs=SandboxPodPrefs(), catalog=catalog)

        by_id = {pod["podId"]: pod for pod in result["pods"]}
        self.assertEqual(by_id["caiuvooekq9qqw"]["gpuStockLevel"], "MEDIUM")
        self.assertEqual(by_id["3i50u1x4pyz0vr"]["gpuStockLevel"], "HIGH")

    def test_status_pod_list_stock_level_is_none_without_catalog(self) -> None:
        fake = _RunPodScript([_pod_5090()])

        result = self._run(sandbox_pod_status, fake, _settings(), prefs=SandboxPodPrefs(), catalog=None)

        self.assertIsNone(result["pods"][0]["gpuStockLevel"])

    def test_status_pod_list_logs_when_gpu_missing_from_catalog(self) -> None:
        # 2026-09-14: 카탈로그 조회는 성공했지만 이 파드의 gpu id가 카탈로그 키와 안 맞는
        # 경우도 VRAM/재고가 조용히 비어 있게 되므로 관측 이벤트가 남아야 한다.
        from backend.app.core import observability

        fake = _RunPodScript([_pod_5090()])
        catalog = {GPU_PRO6000: {"memoryInGb": 96, "securePrice": 2.19, "displayName": "RTX PRO 6000", "stockLevel": "HIGH"}}

        with patch.object(observability.OBSERVABILITY_LOGGER, "info") as info:
            result = self._run(sandbox_pod_status, fake, _settings(), prefs=SandboxPodPrefs(), catalog=catalog)

        self.assertIsNone(result["pods"][0]["gpuStockLevel"])
        payloads = [json.loads(call.args[0]) for call in info.call_args_list]
        failure = next(p for p in payloads if p["event"] == "sandbox_pod.catalog_failure")
        self.assertEqual(failure["Reason"], "gpu_not_in_catalog")
        self.assertEqual(failure["detail"], GPU_5090)

    def test_status_probes_each_running_pod_once_and_skips_detail_when_list_is_complete(self) -> None:
        # 2026-09-13 성능: 표시 파드에 8188 프로브가 두 번 나가던 중복 제거 + 목록 응답이
        # 완전하면 GET /pods/{id} 상세 조회 생략 확인.
        fake = _RunPodScript([_pod_5090(), _pod_pro6000()])
        probe = patch("backend.app.services.sandbox_pod_service._runtime_status", return_value="READY")
        metrics = patch("backend.app.services.sandbox_pod_service._runtime_metrics", return_value={"available": False, "mode": "configuration", "gpus": []})
        with patch("backend.app.services.sandbox_pod_service.urllib.request.urlopen", side_effect=fake), \
                patch("backend.app.services.sandbox_pod_service._fetch_gpu_catalog", return_value=None), \
                probe as probe_mock, metrics as metrics_mock:
            result = sandbox_pod_status(_settings(), prefs=SandboxPodPrefs(selected_pod_id="3i50u1x4pyz0vr"))

        running = [pod for pod in fake.pods.values() if pod["desiredStatus"] == "RUNNING"]
        self.assertEqual(probe_mock.call_count, len(running))
        self.assertEqual(metrics_mock.call_count, 1)
        self.assertEqual(result["runtimeStatus"], "READY")
        self.assertEqual([m for m, p, _ in fake.calls if m == "GET" and p.startswith("/pods/")], [])

    def test_two_phase_loading_status_without_live_then_live_endpoint(self) -> None:
        # 2026-09-13 2단계 로딩: include_live=False는 프로브·지표를 호출하지 않고 pending으로,
        # sandbox_pod_live는 표시 파드의 준비 상태·지표와 파드별 runtimeStatus만 돌려준다.
        fake = _RunPodScript([_pod_5090(), _pod_pro6000()])
        metrics_value = {"available": True, "mode": "live", "gpus": [], "uptimeSeconds": 5}
        with patch("backend.app.services.sandbox_pod_service.urllib.request.urlopen", side_effect=fake), \
                patch("backend.app.services.sandbox_pod_service._fetch_gpu_catalog", return_value=None), \
                patch("backend.app.services.sandbox_pod_service._runtime_status", return_value="READY") as probe_mock, \
                patch("backend.app.services.sandbox_pod_service._runtime_metrics", return_value=metrics_value) as metrics_mock:
            listed = sandbox_pod_status(_settings(), prefs=SandboxPodPrefs(selected_pod_id="3i50u1x4pyz0vr"), include_live=False)
            self.assertEqual(probe_mock.call_count, 0)
            self.assertEqual(metrics_mock.call_count, 0)
            self.assertEqual(listed["runtimeStatus"], "RUNNING")
            self.assertEqual(listed["systemStatus"]["mode"], "pending")
            self.assertEqual([pod["podId"] for pod in listed["pods"]], ["caiuvooekq9qqw", "3i50u1x4pyz0vr"])

            live = sandbox_pod_live(_settings(), prefs=SandboxPodPrefs(selected_pod_id="3i50u1x4pyz0vr"))
            self.assertEqual(live["podId"], "3i50u1x4pyz0vr")
            self.assertEqual(live["runtimeStatus"], "READY")
            self.assertEqual(live["systemStatus"], metrics_value)
            self.assertIn("준비되었습니다", live["message"])
            self.assertEqual({pod["podId"]: pod["runtimeStatus"] for pod in live["pods"]}["3i50u1x4pyz0vr"], "READY")
            self.assertEqual(probe_mock.call_count, 1)
            self.assertEqual(metrics_mock.call_count, 1)

    def test_status_without_running_pod_uses_selected_then_most_recent(self) -> None:
        fake = _RunPodScript([_pod_5090(), _pod_pro6000("EXITED")])
        selected = self._run(sandbox_pod_status, fake, _settings(), prefs=SandboxPodPrefs(selected_pod_id="caiuvooekq9qqw"))
        self.assertEqual(selected["podId"], "caiuvooekq9qqw")
        self.assertIsNone(selected["activePodId"])

        fake = _RunPodScript([_pod_5090(), _pod_pro6000("EXITED")])
        recent = self._run(sandbox_pod_status, fake, _settings(), prefs=SandboxPodPrefs())
        self.assertEqual(recent["podId"], "3i50u1x4pyz0vr")

    def test_8_two_running_pods_flag_conflict_and_block_start(self) -> None:
        fake = _RunPodScript([_pod_5090("RUNNING"), _pod_pro6000("RUNNING")])
        result = self._run(sandbox_pod_status, fake, _settings(), prefs=SandboxPodPrefs())
        self.assertTrue(result["conflict"])
        self.assertEqual(sorted(result["conflictPodIds"]), ["3i50u1x4pyz0vr", "caiuvooekq9qqw"])
        self.assertIsNone(result["activePodId"])

        fake = _RunPodScript([_pod_5090("RUNNING"), _pod_pro6000("RUNNING")])
        with self.assertRaises(SandboxPodConflict) as ctx:
            self._run(start_sandbox_pod, fake, _settings(), None, "caiuvooekq9qqw", prefs=SandboxPodPrefs())
        self.assertEqual(sorted(ctx.exception.running_pod_ids), ["3i50u1x4pyz0vr", "caiuvooekq9qqw"])
        self.assertEqual(fake.posts("/stop"), [])
        self.assertEqual(fake.posts("/start"), [])

    # --- start ---------------------------------------------------------------

    def test_2_switch_stops_running_pod_waits_for_exited_then_starts_selected(self) -> None:
        fake = _RunPodScript([_pod_5090(), _pod_pro6000()])

        result = self._run(start_sandbox_pod, fake, _settings(), None, "caiuvooekq9qqw", prefs=SandboxPodPrefs())

        self.assertEqual([(a["stage"], a["podId"], a["ok"]) for a in result["attempts"]],
                         [("stop", "3i50u1x4pyz0vr", True), ("start", "caiuvooekq9qqw", True)])
        self.assertEqual(result["activePodId"], "caiuvooekq9qqw")
        self.assertEqual(result["selectedPodId"], "caiuvooekq9qqw")
        self.assertEqual(result["gpuTier"], "primary")
        self.assertFalse(result["switched"])
        order = [(m, p) for m, p, _ in fake.calls if m == "POST"]
        self.assertEqual(order, [("POST", "/pods/3i50u1x4pyz0vr/stop"), ("POST", "/pods/caiuvooekq9qqw/start")])

    def test_3_stop_wait_timeout_raises_conflict_without_start(self) -> None:
        stuck = _pod_pro6000()
        fake = _RunPodScript([_pod_5090(), stuck], {
            ("POST", "/pods/3i50u1x4pyz0vr/stop"): [{"id": "3i50u1x4pyz0vr"}],  # accepted but pod stays RUNNING
        })

        with self.assertRaises(SandboxPodConflict) as ctx:
            self._run(start_sandbox_pod, fake, _settings(sandbox_pod_stop_wait_seconds=6), None, "caiuvooekq9qqw", prefs=SandboxPodPrefs())

        self.assertIn("정지 대기", str(ctx.exception))
        self.assertEqual(fake.posts("/start"), [])
        self.assertEqual([a["stage"] for a in ctx.exception.attempts], ["stop"])
        self.assertFalse(ctx.exception.attempts[0]["ok"])

    def test_4_start_no_capacity_with_auto_switch_starts_other_pod(self) -> None:
        fake = _RunPodScript([_pod_5090(), _pod_pro6000("EXITED")], {
            ("POST", "/pods/caiuvooekq9qqw/start"): [_http_error(500, NO_CAP), _http_error(500, NO_CAP)],
        })

        result = self._run(start_sandbox_pod, fake, _settings(), None, "caiuvooekq9qqw",
                           prefs=SandboxPodPrefs(auto_switch_on_start_failure=True))

        stages = [(a["stage"], a["podId"], a["ok"]) for a in result["attempts"]]
        self.assertEqual(stages, [("start", "caiuvooekq9qqw", False), ("start", "caiuvooekq9qqw", False), ("switch", "3i50u1x4pyz0vr", True)])
        self.assertTrue(result["switched"])
        self.assertEqual(result["selectedPodId"], "3i50u1x4pyz0vr")
        self.assertEqual(result["activePodId"], "3i50u1x4pyz0vr")
        # Human-readable messages use the RunPod name first, Pod ID second (spec §2.1).
        self.assertIn("dobedub_comfyUI_Sandbox_RTX PRO 6000 (3i50u1x4pyz0vr)", result["message"])
        self.assertIn("dobedub_comfyUI_Sandbox_RTX 5090 (caiuvooekq9qqw)", result["message"])
        self.assertEqual(result["attempts"][0]["podName"], "dobedub_comfyUI_Sandbox_RTX 5090")
        self.assertEqual(fake.posts("/pods"), [])  # no create

    def test_5_start_failure_without_auto_switch_creates_with_gpu_fallback(self) -> None:
        created = {"id": "newpod00000001", "desiredStatus": "CREATED", "gpuTypeIds": [GPU_PRO4500],
                   "networkVolume": {"id": VOLUME}, "ports": ["8188/http"], "costPerHr": 0.72}
        fake = _RunPodScript([_pod_5090(), _pod_pro6000("EXITED")], {
            ("GET", "/pods"): [[_pod_5090(), _pod_pro6000("EXITED")]],
            ("POST", "/pods/caiuvooekq9qqw/start"): [_http_error(500, NO_CAP)],
            ("POST", "/pods"): [_http_error(500, NO_CAP), created],
        })
        fake.pods[created["id"]] = created

        result = self._run(start_sandbox_pod, fake, _settings(sandbox_pod_start_retry_count=0), None, "caiuvooekq9qqw",
                           prefs=SandboxPodPrefs(auto_switch_on_start_failure=False))

        stages = [(a["stage"], a.get("gpuTypeId"), a["ok"]) for a in result["attempts"]]
        self.assertEqual(stages, [("start", GPU_5090, False), ("create", GPU_5090, False), ("create", GPU_PRO4500, True)])
        self.assertEqual(result["gpuTier"], "fallback")
        self.assertEqual(result["gpuTypeId"], GPU_PRO4500)
        self.assertEqual(result["createdBy"], "auto-fallback")
        self.assertEqual(result["resolvedBy"], f"create:{GPU_PRO4500}")
        self.assertEqual(result["selectedPodId"], "newpod00000001")
        bodies = [body for _, body in fake.posts("/pods")]
        self.assertEqual([b["gpuTypeIds"] for b in bodies], [[GPU_5090], [GPU_PRO4500]])
        # REST v1 PodCreateInput: only known keys, no REST v2-only flags.
        allowed = {"name", "templateId", "networkVolumeId", "gpuTypeIds", "gpuCount"}
        self.assertTrue(all(set(b) <= allowed for b in bodies), bodies)
        self.assertTrue(all("dataCenterIds" not in b for b in bodies))
        # No catalog patched in → local short label: <DEPLOY_NAME>_<GPU label>.
        self.assertEqual([b["name"] for b in bodies], ["dobedub_comfyUI_Sandbox_RTX 5090", "dobedub_comfyUI_Sandbox_RTX PRO 4500"])
        self.assertIn("RTX PRO 4500", result["message"])
        self.assertEqual(fake.posts("/pods/3i50u1x4pyz0vr/start"), [])

    def test_6_create_config_error_stops_immediately(self) -> None:
        fake = _RunPodScript([_pod_5090("TERMINATED")], {
            ("GET", "/pods"): [[_pod_5090("TERMINATED")]],
            ("POST", "/pods"): [_http_error(400, '{"error":"templateId invalid"}')],
        })

        with self.assertRaises(ValueError):
            self._run(start_sandbox_pod, fake, _settings(), None, None, prefs=SandboxPodPrefs())

        self.assertEqual(len(fake.posts("/pods")), 1)

    def test_7_every_stage_fails_raises_unavailable_with_full_attempts(self) -> None:
        fake = _RunPodScript([_pod_5090(), _pod_pro6000("EXITED")], {
            ("POST", "/pods/caiuvooekq9qqw/start"): [_http_error(500, NO_CAP)],
            ("POST", "/pods/3i50u1x4pyz0vr/start"): [_http_error(500, NO_CAP)],
            ("POST", "/pods"): [_http_error(500, NO_CAP)] * 3,
        })

        with self.assertRaises(SandboxPodUnavailable) as ctx:
            self._run(start_sandbox_pod, fake, _settings(sandbox_pod_start_retry_count=0), None, "caiuvooekq9qqw",
                      prefs=SandboxPodPrefs())

        stages = [a["stage"] for a in ctx.exception.attempts]
        self.assertEqual(stages, ["start", "switch", "create", "create", "create"])
        self.assertEqual(ctx.exception.retry_after_seconds, 300)
        self.assertIn("RTX 5090", str(ctx.exception))

    def test_9_no_fallback_configured_creates_once_like_legacy(self) -> None:
        fake = _RunPodScript([_pod_5090()], {
            ("POST", "/pods/caiuvooekq9qqw/start"): [_http_error(500, NO_CAP)],
            ("POST", "/pods"): [_http_error(500, NO_CAP)],
        })

        with self.assertRaises(SandboxPodUnavailable) as ctx:
            self._run(start_sandbox_pod, fake, _settings(sandbox_pod_gpu_fallback_type_ids=(), sandbox_pod_start_retry_count=0),
                      None, None, prefs=SandboxPodPrefs())

        self.assertEqual([a.get("gpuTypeId") for a in ctx.exception.attempts if a["stage"] == "create"], [GPU_5090])

    def test_10_vram_filter_skips_small_gpu_then_continues(self) -> None:
        created = {"id": "newpod00000002", "desiredStatus": "CREATED", "gpuTypeIds": [GPU_PRO6000],
                   "networkVolume": {"id": VOLUME}, "ports": ["8188/http"]}
        fake = _RunPodScript([_pod_5090("TERMINATED")], {
            ("GET", "/pods"): [[_pod_5090("TERMINATED")]],
            ("POST", "/pods"): [_http_error(500, NO_CAP), created],
        })
        fake.pods[created["id"]] = created
        catalog = {GPU_5090: {"memoryInGb": 32}, "NVIDIA RTX A4000": {"memoryInGb": 16}, GPU_PRO6000: {"memoryInGb": 96}}

        result = self._run(start_sandbox_pod, fake,
                           _settings(sandbox_pod_gpu_fallback_type_ids=("NVIDIA RTX A4000", GPU_PRO6000)),
                           None, None, prefs=SandboxPodPrefs(), catalog=catalog)

        skipped = [a for a in result["attempts"] if a.get("skipped") == "vram"]
        self.assertEqual(skipped[0]["gpuTypeId"], "NVIDIA RTX A4000")
        self.assertEqual(result["gpuTypeId"], GPU_PRO6000)

    def test_create_names_pod_with_catalog_display_name(self) -> None:
        created = {"id": "newpod00000003", "desiredStatus": "CREATED", "gpuTypeIds": [GPU_PRO6000],
                   "networkVolume": {"id": VOLUME}, "ports": ["8188/http"]}
        fake = _RunPodScript([_pod_5090("TERMINATED")], {
            ("GET", "/pods"): [[_pod_5090("TERMINATED")]],
            ("POST", "/pods"): [_http_error(500, NO_CAP), created],
        })
        fake.pods[created["id"]] = created
        catalog = {GPU_5090: {"memoryInGb": 32, "displayName": "RTX 5090"},
                   GPU_PRO6000: {"memoryInGb": 96, "displayName": "RTX PRO 6000 WK"}}

        result = self._run(start_sandbox_pod, fake, _settings(sandbox_pod_gpu_fallback_type_ids=(GPU_PRO6000,)),
                           None, None, prefs=SandboxPodPrefs(), catalog=catalog)

        self.assertEqual([b["name"] for _, b in fake.posts("/pods")],
                         ["dobedub_comfyUI_Sandbox_RTX 5090", "dobedub_comfyUI_Sandbox_RTX PRO 6000 WK"])
        self.assertEqual(result["selectedPodId"], "newpod00000003")

    def test_status_flags_missing_selected_pod_after_migration(self) -> None:
        fake = _RunPodScript([_pod_5090(), _pod_pro6000()])
        result = self._run(sandbox_pod_status, fake, _settings(), prefs=SandboxPodPrefs(selected_pod_id="oldpodgone0000"))
        self.assertTrue(result["selectedPodMissing"])
        self.assertIn("찾을 수 없습니다", result["message"])
        self.assertEqual(result["activePodName"], "dobedub_comfyUI_Sandbox_RTX PRO 6000")

    def test_conflict_message_uses_pod_names(self) -> None:
        fake = _RunPodScript([_pod_5090("RUNNING"), _pod_pro6000("RUNNING")])
        with self.assertRaises(SandboxPodConflict) as ctx:
            self._run(start_sandbox_pod, fake, _settings(), None, None, prefs=SandboxPodPrefs())
        self.assertIn("dobedub_comfyUI_Sandbox_RTX 5090 (caiuvooekq9qqw)", str(ctx.exception))

    def test_status_reads_v1_pod_shape_gpu_object_and_v2_catalog(self) -> None:
        # Real REST v1 detail payload: no gpuTypeIds, GPU under `gpu` (2026-09-12 observed).
        v1_pod = {
            "id": "caiuvooekq9qqw", "name": "dobedub_comfyUI_Sandbox_RTX 5090", "desiredStatus": "EXITED",
            "templateId": TEMPLATE, "networkVolume": {"id": VOLUME}, "costPerHr": 0.99, "memoryInGb": 60,
            "gpu": {"id": GPU_5090, "count": 1, "displayName": "RTX 5090", "securePrice": 0.99},
            "machine": {"gpuTypeId": GPU_5090, "gpuType": {"id": GPU_5090, "displayName": "RTX 5090"}},
            "ports": ["8188/http", "8888/http"],
        }
        fake = _RunPodScript([v1_pod])
        catalog = {GPU_5090: {"memoryInGb": 32, "securePrice": 0.99, "displayName": "RTX 5090"}}

        result = self._run(sandbox_pod_status, fake, _settings(), prefs=SandboxPodPrefs(), catalog=catalog)

        pod = result["pods"][0]
        self.assertEqual(pod["gpuTypeId"], GPU_5090)
        self.assertEqual(pod["gpuLabel"], "RTX 5090")
        self.assertEqual(pod["gpuTier"], "primary")
        self.assertEqual(pod["vramGb"], 32)
        self.assertEqual(result["gpuTypeId"], GPU_5090)

    # --- policy A: replace stopped Pods of the same GPU after create ---------------

    def test_create_terminates_stopped_pod_of_same_gpu_only(self) -> None:
        created = {"id": "owzsooe4zwewnz", "desiredStatus": "CREATED", "gpuTypeIds": [GPU_5090],
                   "networkVolume": {"id": VOLUME}, "ports": ["8188/http"], "name": "dobedub_comfyUI_Sandbox_RTX 5090"}
        fake = _RunPodScript([_pod_5090(), _pod_pro6000("EXITED")], {
            ("GET", "/pods"): [[_pod_5090(), _pod_pro6000("EXITED")]],
            ("POST", "/pods/caiuvooekq9qqw/start"): [_http_error(500, NO_CAP)],
            ("POST", "/pods/3i50u1x4pyz0vr/start"): [_http_error(500, NO_CAP)],
            ("POST", "/pods"): [created],
        })
        fake.pods[created["id"]] = created

        result = self._run(start_sandbox_pod, fake, _settings(sandbox_pod_start_retry_count=0), None, "caiuvooekq9qqw",
                           prefs=SandboxPodPrefs(replace_same_gpu_pods=True))

        self.assertEqual(fake.deletes(), ["/pods/caiuvooekq9qqw"])  # same GPU, EXITED → gone; PRO 6000 untouched
        self.assertEqual([p["podId"] for p in result["pods"]], ["3i50u1x4pyz0vr", "owzsooe4zwewnz"])
        terminated = [a for a in result["attempts"] if a["stage"] == "terminate"]
        self.assertEqual([(a["podId"], a["ok"], a["podName"]) for a in terminated], [("caiuvooekq9qqw", True, "dobedub_comfyUI_Sandbox_RTX 5090")])
        self.assertEqual(result["selectedPodId"], "owzsooe4zwewnz")

    def test_create_keeps_stopped_pod_when_replace_policy_off(self) -> None:
        created = {"id": "owzsooe4zwewnz", "desiredStatus": "CREATED", "gpuTypeIds": [GPU_5090], "networkVolume": {"id": VOLUME}, "ports": []}
        fake = _RunPodScript([_pod_5090()], {
            ("GET", "/pods"): [[_pod_5090()]],
            ("POST", "/pods/caiuvooekq9qqw/start"): [_http_error(500, NO_CAP)],
            ("POST", "/pods"): [created],
        })
        fake.pods[created["id"]] = created

        result = self._run(start_sandbox_pod, fake, _settings(sandbox_pod_start_retry_count=0), None, "caiuvooekq9qqw",
                           prefs=SandboxPodPrefs(replace_same_gpu_pods=False, auto_switch_on_start_failure=False))

        self.assertEqual(fake.deletes(), [])
        self.assertEqual(len(result["pods"]), 2)

    def test_create_never_terminates_running_pod_of_same_gpu(self) -> None:
        # Defensive: a RUNNING same-GPU Pod cannot exist at create time (invariant), but
        # the policy must still never delete anything that is not EXITED.
        created = {"id": "newpod00000009", "desiredStatus": "CREATED", "gpuTypeIds": [GPU_5090], "networkVolume": {"id": VOLUME}, "ports": []}
        pods = [{**_pod_5090("TERMINATED")}]
        fake = _RunPodScript(pods, {("GET", "/pods"): [pods], ("POST", "/pods"): [created]})
        fake.pods[created["id"]] = created
        result = self._run(start_sandbox_pod, fake, _settings(), None, None, prefs=SandboxPodPrefs())
        self.assertEqual(fake.deletes(), [])
        self.assertEqual(result["selectedPodId"], "newpod00000009")

    def test_create_records_failed_terminate_and_continues(self) -> None:
        created = {"id": "owzsooe4zwewnz", "desiredStatus": "CREATED", "gpuTypeIds": [GPU_5090], "networkVolume": {"id": VOLUME}, "ports": []}
        fake = _RunPodScript([_pod_5090()], {
            ("GET", "/pods"): [[_pod_5090()]],
            ("POST", "/pods/caiuvooekq9qqw/start"): [_http_error(500, NO_CAP)],
            ("POST", "/pods"): [created],
            ("DELETE", "/pods/caiuvooekq9qqw"): [_http_error(500, "delete failed")],
        })
        fake.pods[created["id"]] = created

        result = self._run(start_sandbox_pod, fake, _settings(sandbox_pod_start_retry_count=0), None, "caiuvooekq9qqw",
                           prefs=SandboxPodPrefs(auto_switch_on_start_failure=False))

        terminated = [a for a in result["attempts"] if a["stage"] == "terminate"]
        self.assertFalse(terminated[0]["ok"])
        self.assertEqual(len(result["pods"]), 2)  # kept in the list; start itself still succeeded
        self.assertEqual(result["activePodId"], "owzsooe4zwewnz")

    # --- manual terminate ----------------------------------------------------------

    def test_terminate_deletes_stopped_pod_and_moves_selection(self) -> None:
        fake = _RunPodScript([_pod_5090(), _pod_pro6000("EXITED")])
        result = self._run(terminate_sandbox_pod, fake, _settings(), None, "caiuvooekq9qqw", prefs=SandboxPodPrefs(selected_pod_id="caiuvooekq9qqw"))
        self.assertEqual(fake.deletes(), ["/pods/caiuvooekq9qqw"])
        self.assertEqual(result["terminatedPodId"], "caiuvooekq9qqw")
        self.assertEqual([p["podId"] for p in result["pods"]], ["3i50u1x4pyz0vr"])
        self.assertEqual(result["selectedPodId"], "3i50u1x4pyz0vr")
        self.assertIn("dobedub_comfyUI_Sandbox_RTX 5090 (caiuvooekq9qqw)", result["message"])

    def test_terminate_refuses_running_pod(self) -> None:
        fake = _RunPodScript([_pod_5090(), _pod_pro6000()])
        with self.assertRaises(ValueError):
            self._run(terminate_sandbox_pod, fake, _settings(), None, "3i50u1x4pyz0vr", prefs=SandboxPodPrefs())
        self.assertEqual(fake.deletes(), [])

    def test_11_start_on_running_selected_pod_is_idempotent(self) -> None:
        fake = _RunPodScript([_pod_5090(), _pod_pro6000()])

        result = self._run(start_sandbox_pod, fake, _settings(), None, "3i50u1x4pyz0vr", prefs=SandboxPodPrefs())

        self.assertEqual(result["attempts"], [])
        self.assertEqual(fake.posts("/stop"), [])
        self.assertEqual([p for p, _ in fake.posts("/start")], ["/pods/3i50u1x4pyz0vr/start"])

    def test_12_start_accepted_but_pod_stays_exited_falls_through(self) -> None:
        fake = _RunPodScript([_pod_5090(), _pod_pro6000("EXITED")], {
            ("POST", "/pods/caiuvooekq9qqw/start"): [{"id": "caiuvooekq9qqw"}],  # 200 but no GPU assigned
        })

        result = self._run(start_sandbox_pod, fake, _settings(sandbox_pod_start_retry_count=0), None, "caiuvooekq9qqw",
                           prefs=SandboxPodPrefs())

        self.assertEqual(result["attempts"][0]["stage"], "start")
        self.assertFalse(result["attempts"][0]["ok"])
        self.assertIn("stayed EXITED", result["attempts"][0]["error"])
        self.assertEqual(result["attempts"][1]["stage"], "switch")
        self.assertTrue(result["switched"])

    def test_13_unknown_pod_id_is_rejected(self) -> None:
        fake = _RunPodScript([_pod_5090()])
        with self.assertRaises(ValueError):
            self._run(start_sandbox_pod, fake, _settings(), None, "nope", prefs=SandboxPodPrefs())

    # --- stop ----------------------------------------------------------------

    def test_stop_targets_given_pod_or_active_pod(self) -> None:
        fake = _RunPodScript([_pod_5090(), _pod_pro6000()])
        result = self._run(stop_sandbox_pod, fake, _settings(), None, None, prefs=SandboxPodPrefs())
        self.assertEqual(result["stoppedPodId"], "3i50u1x4pyz0vr")
        self.assertEqual(result["attempts"][0]["stage"], "stop")

        fake = _RunPodScript([_pod_5090("RUNNING"), _pod_pro6000("RUNNING")])
        result = self._run(stop_sandbox_pod, fake, _settings(), None, "caiuvooekq9qqw", prefs=SandboxPodPrefs())
        self.assertEqual(result["stoppedPodId"], "caiuvooekq9qqw")
        self.assertFalse(result["conflict"])

        fake = _RunPodScript([_pod_5090("RUNNING"), _pod_pro6000("RUNNING")])
        with self.assertRaises(ValueError):
            self._run(stop_sandbox_pod, fake, _settings(), None, None, prefs=SandboxPodPrefs())

    # --- 2026-09-13 성능: 파드 목록 조회 캐시 ---------------------------------

    def test_resolve_pods_list_cache_avoids_duplicate_get_pods_calls(self) -> None:
        fake = _RunPodScript([_pod_5090(), _pod_pro6000()])
        settings = _settings()

        def list_calls() -> list:
            return [c for c in fake.calls if c[0] == "GET" and c[1].startswith("/pods?")]

        self._run(sandbox_pod_status, fake, settings, prefs=SandboxPodPrefs())
        self.assertEqual(len(list_calls()), 1)

        # 짧은 TTL 안의 두 번째 조회는 캐시를 재사용하고 RunPod GET /pods를 다시 부르지 않는다.
        self._run(sandbox_pod_status, fake, settings, prefs=SandboxPodPrefs())
        self.assertEqual(len(list_calls()), 1)

        # Stop처럼 상태를 바꾸는 액션은 항상 use_cache=False로 최신 목록을 다시 읽는다.
        self._run(stop_sandbox_pod, fake, settings, None, "3i50u1x4pyz0vr", prefs=SandboxPodPrefs())
        self.assertEqual(len(list_calls()), 2)

        # 액션 이후 캐시를 비웠으므로 다음 상태 조회는 새로 GET /pods를 부른다.
        self._run(sandbox_pod_status, fake, settings, prefs=SandboxPodPrefs())
        self.assertEqual(len(list_calls()), 3)


class SandboxPodCatalogTests(unittest.TestCase):
    def setUp(self) -> None:
        service._catalog_cache["at"] = 0.0
        service._catalog_cache["value"] = None

    @patch("backend.app.services.sandbox_pod_service._request")
    def test_catalog_reads_rest_v2_gpu_catalog_and_caches(self, request: object) -> None:
        request.return_value = {"gpus": [
            {"id": GPU_PRO4500, "name": "RTX PRO 4500", "memory": 32, "price": {"secure": 0.72, "community": 0.34}, "availability": "HIGH"},
            {"id": "NVIDIA L4", "name": "L4", "memory": 24, "price": {"secure": 0.49}},
        ]}

        catalog = service._fetch_gpu_catalog(_settings())

        # 2026-09-13: 재고(availability)를 함께 받기 위해 include=AVAILABILITY&product=POD를 붙인다.
        self.assertEqual(request.call_args.args[2], "/catalog/gpus?include=AVAILABILITY&product=POD")
        self.assertEqual(request.call_args.kwargs.get("base_url"), "https://api.runpod.io/v2")
        self.assertEqual(
            catalog[GPU_PRO4500],
            {"memoryInGb": 32, "securePrice": 0.72, "displayName": "RTX PRO 4500", "stockLevel": "HIGH"},
        )
        # availability가 없는 항목은 stockLevel이 None(표시 안 함)이어야 한다.
        self.assertIsNone(catalog["NVIDIA L4"]["stockLevel"])
        request.side_effect = AssertionError("should be cached")
        self.assertEqual(service._fetch_gpu_catalog(_settings())[GPU_PRO4500]["memoryInGb"], 32)

    @patch("backend.app.services.sandbox_pod_service._request", side_effect=SandboxPodApiError(403, "forbidden"))
    def test_catalog_failure_returns_none(self, _: object) -> None:
        self.assertIsNone(service._fetch_gpu_catalog(_settings()))

    @patch("backend.app.services.sandbox_pod_service._request", side_effect=SandboxPodApiError(403, "forbidden"))
    def test_catalog_failure_emits_observability_event(self, _: object) -> None:
        # 2026-09-14: 카탈로그 조회 실패는 조용히 삼켜지더라도(VRAM/재고는 그대로 비어
        # 있어야 함) 관측 이벤트로는 반드시 남아야 진단이 가능하다.
        from backend.app.core import observability

        with patch.object(observability.OBSERVABILITY_LOGGER, "info") as info:
            self.assertIsNone(service._fetch_gpu_catalog(_settings()))

        payload = json.loads(info.call_args.args[0])
        self.assertEqual(payload["event"], "sandbox_pod.catalog_failure")
        self.assertEqual(payload["Reason"], "SandboxPodApiError")
        self.assertEqual(payload["SandboxPodCatalogFailureCount"], 1)

    @patch("backend.app.services.sandbox_pod_service.urllib.request.urlopen")
    def test_request_wraps_non_json_body(self, urlopen: object) -> None:
        class Html:
            status = 200
            def __enter__(self): return self
            def __exit__(self, *_): return None
            def read(self): return b"<html>docs</html>"
        urlopen.return_value = Html()
        with self.assertRaises(SandboxPodApiError):
            service._request(_settings(), "GET", "/pods")


class SandboxPodObservabilityTests(unittest.TestCase):
    def test_attempt_emits_emf_payload(self) -> None:
        from backend.app.core import observability

        with patch.object(observability.OBSERVABILITY_LOGGER, "info") as info:
            observability.observe_sandbox_pod_attempt(stage="create", pod_id=None, gpu_type_id=GPU_5090, ok=False,
                                                      error="HTTP 500: no instances", skipped=None)
            observability.observe_sandbox_pod_event(kind="fallback", pod_id="x", gpu_type_id=GPU_PRO4500)

        attempt = json.loads(info.call_args_list[0].args[0])
        self.assertEqual(attempt["event"], "sandbox_pod.attempt")
        self.assertEqual(attempt["SandboxPodStartAttemptCount"], 1)
        self.assertEqual(attempt["Ok"], "false")
        self.assertEqual(attempt["_aws"]["CloudWatchMetrics"][0]["Dimensions"], [["Environment", "Stage", "GpuTypeId", "Ok"]])
        event = json.loads(info.call_args_list[1].args[0])
        self.assertEqual(event["SandboxPodFallbackCount"], 1)
