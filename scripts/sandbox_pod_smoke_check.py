#!/usr/bin/env python3
"""Read-only smoke check for the multi-pod Sandbox Pod admin API on a running local server.

Usage (server started with `python3 scripts/run_local.py`):

    python3 scripts/sandbox_pod_smoke_check.py                 # GET status only (no RunPod writes)
    python3 scripts/sandbox_pod_smoke_check.py --select <podId> # also round-trips /select + /settings (DB only)

It never calls /start or /stop — those change real Pods and cost money.
Environment: BASE_URL (default http://127.0.0.1:8787), SMOKE_USER / SMOKE_PASSWORD
(default local admin dobedub / password).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request


BASE_URL = os.environ.get("BASE_URL", "http://127.0.0.1:8787").rstrip("/")


def request_json(path: str, *, method: str = "GET", body: dict | None = None, headers: dict | None = None) -> tuple[int, dict]:
    request = urllib.request.Request(
        f"{BASE_URL}{path}",
        data=json.dumps(body).encode("utf-8") if body is not None else None,
        method=method,
        headers={"Content-Type": "application/json", **(headers or {})},
    )
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            payload = response.read().decode("utf-8")
            return response.status, (json.loads(payload) if payload.strip() else {})
    except urllib.error.HTTPError as exc:
        payload = exc.read().decode("utf-8", errors="replace")
        try:
            return exc.code, json.loads(payload)
        except ValueError:
            return exc.code, {"detail": payload}


def login_headers() -> dict[str, str]:
    user = os.environ.get("SMOKE_USER", "dobedub")
    password = os.environ.get("SMOKE_PASSWORD", "password")
    status, payload = request_json("/api/auth/login", method="POST", body={"id": user, "password": password})
    if status != 200:
        raise SystemExit(f"login failed ({status}): {payload}")
    return {"Authorization": f"Bearer {payload['accessToken']}"}


def check(condition: bool, label: str, detail: str = "") -> bool:
    mark = "OK " if condition else "!! "
    print(f"  {mark} {label}{f' — {detail}' if detail else ''}")
    return condition


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--select", metavar="POD_ID", help="round-trip /select and /settings for this Pod (DB only)")
    args = parser.parse_args()

    headers = login_headers()
    status, payload = request_json("/api/admin/sandbox-pod", headers=headers)
    print(f"GET /api/admin/sandbox-pod → {status}")
    if status != 200:
        raise SystemExit(json.dumps(payload, ensure_ascii=False, indent=2))
    if not payload.get("configured"):
        raise SystemExit(f"Sandbox Pod not configured: {payload.get('message')}")

    pods = payload.get("pods") or []
    print(f"\nPods on volume ({len(pods)}): selected={payload.get('selectedPodId')} active={payload.get('activePodId')} conflict={payload.get('conflict')}")
    print(f"  {'POD ID':<16} {'GPU':<34} {'TIER':<9} {'VRAM':>6} {'RAM':>6} {'$/h':>6} {'STATUS':<10} JUPYTER")
    for pod in pods:
        jupyter = next((s for s in pod.get("httpServices") or [] if s.get("internalPort") == 8888), None)
        auth = "auth" if jupyter and jupyter.get("authRequired") else ("open" if jupyter else "-")
        print(
            f"  {pod.get('podId', ''):<16} {str(pod.get('gpuTypeId') or '-')[:34]:<34} {str(pod.get('gpuTier') or '-'):<9} "
            f"{str(pod.get('vramGb') or '-'):>6} {str(pod.get('ramGb') or '-'):>6} {str(pod.get('pricePerHr') or '-'):>6} "
            f"{str(pod.get('desiredStatus') or '-'):<10} {auth}"
        )

    print("\nField checks (RunPod response shape):")
    ok = True
    ok &= check(bool(pods), "at least one Pod listed on the network volume", payload.get("message", ""))
    ok &= check(all(pod.get("gpuTypeId") for pod in pods), "gpuTypeId present on every Pod (gpuTypeIds / gpuTypeId)")
    ok &= check(all(pod.get("pricePerHr") is not None for pod in pods), "pricePerHr present (pod.costPerHr)")
    ok &= check(all(pod.get("ramGb") is not None for pod in pods), "ramGb present (pod.memoryInGb)")
    ok &= check(any(pod.get("vramGb") is not None for pod in pods), "vramGb resolved from GraphQL gpuTypes catalog (memoryInGb; needs GraphQL-capable key)")
    ok &= check(payload.get("resolvedBy") == "network-volume", "legacy fields resolved by network-volume", str(payload.get("resolvedBy")))
    ok &= check("settings" in payload and "autoSwitchOnStartFailure" in payload["settings"], "settings block present")
    ok &= check(isinstance(payload.get("attempts"), list), "attempts list present (GET → [])")
    running = [pod["podId"] for pod in pods if str(pod.get("desiredStatus") or "").upper() in {"RUNNING", "STARTING", "PENDING", "CREATED", "RESTARTING"}]
    ok &= check(len(running) <= 1, "single-running invariant holds", f"running={running}")
    if payload.get("conflict"):
        print("  !! conflict=true — 두 파드가 동시에 실행 중입니다. 화면의 '선택 파드만 남기고 정지'로 해소하세요.")

    if args.select:
        print(f"\nPOST /select {args.select} (DB only)")
        status, selected = request_json("/api/admin/sandbox-pod/select", method="POST", body={"podId": args.select}, headers=headers)
        ok &= check(status == 200 and selected.get("selectedPodId") == args.select, "selection persisted", f"status={status}")
        current = selected.get("settings") or payload.get("settings") or {}
        status, saved = request_json(
            "/api/admin/sandbox-pod/settings",
            method="PUT",
            body={"autoSwitchOnStartFailure": bool(current.get("autoSwitchOnStartFailure", True)), "podPriority": [pod["podId"] for pod in pods]},
            headers=headers,
        )
        ok &= check(status == 200 and saved.get("podPriority") == [pod["podId"] for pod in pods], "settings round-trip", f"status={status}")

    print("\nNext (manual, costs money): open http://127.0.0.1:8787/studio → ADMIN → Sandbox Pod, pick a Pod, press Start/전환 후 시작.")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
