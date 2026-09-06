#!/usr/bin/env python3
"""Start the local DOBEDUB service on localhost:8787 in the background."""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TMP_DIR = PROJECT_ROOT / "tmp"
PID_FILE = TMP_DIR / "local-server.pid"
LOG_FILE = TMP_DIR / "local-server.log"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = "8787"
DEFAULT_DATABASE_URL = "sqlite:///./data/dobedub-studio.db"


def main() -> int:
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    host = os.environ.get("HOST", DEFAULT_HOST)
    port = os.environ.get("PORT", DEFAULT_PORT)
    database_url = os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL)

    listening = listening_pids(port)
    if listening:
        print(f"Local service already listening on {host}:{port} (pid: {', '.join(listening)}).")
        PID_FILE.write_text(listening[0] + "\n", encoding="utf-8")
        return 0

    subprocess.run(["npm", "--prefix", "frontend", "run", "build"], cwd=PROJECT_ROOT, check=True)

    env = os.environ.copy()
    env.setdefault("HOST", host)
    env.setdefault("PORT", port)
    env.setdefault("DATABASE_URL", database_url)
    with LOG_FILE.open("ab") as log:
        process = subprocess.Popen(
            [sys.executable, "scripts/run_local.py"],
            cwd=PROJECT_ROOT,
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    PID_FILE.write_text(f"{process.pid}\n", encoding="utf-8")

    deadline = time.time() + 20
    while time.time() < deadline:
        if process.poll() is not None:
            print(f"Local service exited early with code {process.returncode}. See {LOG_FILE}.")
            return process.returncode or 1
        if port_accepts_connections(host, int(port)):
            print(f"Local service started: http://{host}:{port}")
            print(f"PID: {process.pid}")
            print(f"Log: {LOG_FILE}")
            return 0
        time.sleep(0.25)

    print(f"Local service is starting but did not answer within 20 seconds. See {LOG_FILE}.")
    print(f"PID: {process.pid}")
    return 0


def listening_pids(port: str) -> list[str]:
    result = subprocess.run(
        ["lsof", f"-tiTCP:{port}", "-sTCP:LISTEN"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def port_accepts_connections(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.5):
            return True
    except OSError:
        return False


if __name__ == "__main__":
    raise SystemExit(main())
