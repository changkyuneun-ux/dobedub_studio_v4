#!/usr/bin/env python3
"""Stop the local DOBEDUB service running on localhost:8787."""

from __future__ import annotations

import os
import signal
import subprocess
import time
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TMP_DIR = PROJECT_ROOT / "tmp"
PID_FILE = TMP_DIR / "local-server.pid"
DEFAULT_PORT = "8787"


def main() -> int:
    port = os.environ.get("PORT", DEFAULT_PORT)
    pids = set(pid_file_pids()) | set(listening_pids(port))
    if not pids:
        remove_pid_file()
        print(f"No local service is listening on 127.0.0.1:{port}.")
        return 0

    for pid in sorted(pids):
        terminate(pid)
    wait_until_stopped(pids, port)
    remaining = set(listening_pids(port))
    for pid in sorted(remaining):
        kill(pid)
    remove_pid_file()

    if remaining:
        print(f"Stopped local service on 127.0.0.1:{port} (pid: {', '.join(sorted(pids | remaining))}).")
    else:
        print(f"Stopped local service on 127.0.0.1:{port} (pid: {', '.join(sorted(pids))}).")
    return 0


def pid_file_pids() -> list[str]:
    if not PID_FILE.exists():
        return []
    return [line.strip() for line in PID_FILE.read_text(encoding="utf-8").splitlines() if line.strip()]


def listening_pids(port: str) -> list[str]:
    result = subprocess.run(
        ["lsof", f"-tiTCP:{port}", "-sTCP:LISTEN"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def terminate(pid: str) -> None:
    try:
        os.kill(int(pid), signal.SIGTERM)
    except (ProcessLookupError, ValueError):
        return


def kill(pid: str) -> None:
    try:
        os.kill(int(pid), signal.SIGKILL)
    except (ProcessLookupError, ValueError):
        return


def wait_until_stopped(pids: set[str], port: str) -> None:
    deadline = time.time() + 5
    while time.time() < deadline:
        alive = set(listening_pids(port)) | {pid for pid in pids if process_exists(pid)}
        if not alive:
            return
        time.sleep(0.2)


def process_exists(pid: str) -> bool:
    try:
        os.kill(int(pid), 0)
    except (ProcessLookupError, ValueError):
        return False
    return True


def remove_pid_file() -> None:
    try:
        PID_FILE.unlink()
    except FileNotFoundError:
        return


if __name__ == "__main__":
    raise SystemExit(main())
