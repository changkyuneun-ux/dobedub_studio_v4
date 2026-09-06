from __future__ import annotations

import json
import importlib.util
import types
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_npm_local_scripts_bind_backend_to_localhost_8787():
    package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))

    assert package["scripts"]["start"] == "HOST=127.0.0.1 PORT=8787 python3.12 scripts/run_local.py"
    assert package["scripts"]["local"] == (
        "npm --prefix frontend run build && HOST=127.0.0.1 PORT=8787 python3.12 scripts/run_local.py"
    )
    assert package["scripts"]["local:up"] == "python3.12 scripts/start_local.py"
    assert package["scripts"]["local:down"] == "python3.12 scripts/stop_local.py"
    assert package["scripts"]["local:restart"] == "npm run local:down && npm run local:up"


def test_run_local_defaults_to_localhost_8787_when_called_directly():
    source = (ROOT / "scripts" / "run_local.py").read_text(encoding="utf-8")

    assert 'host = os.environ.get("HOST", "127.0.0.1")' in source
    assert 'port = int(os.environ.get("PORT", "8787"))' in source


def test_run_local_can_reexec_python312_before_third_party_imports(monkeypatch):
    run_local = _load_script("run_local")
    calls = []

    monkeypatch.setattr(run_local, "_required_modules_available", lambda: False)
    monkeypatch.setattr(run_local.shutil, "which", lambda name: "/usr/local/bin/python3.12" if name == "python3.12" else None)
    monkeypatch.setattr(run_local, "_candidate_has_required_modules", lambda path: str(path) == "/usr/local/bin/python3.12")
    monkeypatch.setattr(run_local.sys, "executable", "/usr/local/bin/python3")
    monkeypatch.setattr(run_local.sys, "argv", [str(ROOT / "scripts" / "run_local.py")])
    monkeypatch.setattr(run_local.os, "execv", lambda executable, argv: calls.append((executable, argv)))

    run_local.ensure_local_python_runtime()

    assert calls == [
        ("/usr/local/bin/python3.12", ["/usr/local/bin/python3.12", str(ROOT / "scripts" / "run_local.py")])
    ]


def test_run_local_skips_python_candidates_without_required_modules(monkeypatch):
    run_local = _load_script("run_local")
    calls = []
    candidates = [
        Path("/broken/bin/python3.12"),
        Path("/Library/Frameworks/Python.framework/Versions/3.12/bin/python3"),
    ]

    monkeypatch.setattr(run_local, "_required_modules_available", lambda: False)
    monkeypatch.setattr(run_local, "_python_candidates", lambda: candidates)
    monkeypatch.setattr(run_local, "_candidate_has_required_modules", lambda path: "Library" in str(path))
    monkeypatch.setattr(run_local.sys, "executable", "/broken/bin/python3.12")
    monkeypatch.setattr(run_local.sys, "argv", [str(ROOT / "scripts" / "run_local.py")])
    monkeypatch.setattr(run_local.os, "execv", lambda executable, argv: calls.append((executable, argv)))

    run_local.ensure_local_python_runtime()

    assert calls == [
        (
            "/Library/Frameworks/Python.framework/Versions/3.12/bin/python3",
            ["/Library/Frameworks/Python.framework/Versions/3.12/bin/python3", str(ROOT / "scripts" / "run_local.py")],
        )
    ]


def test_local_up_down_scripts_share_the_local_service_contract():
    start = _load_script("start_local")
    stop = _load_script("stop_local")

    assert start.DEFAULT_HOST == "127.0.0.1"
    assert start.DEFAULT_PORT == "8787"
    assert start.DEFAULT_DATABASE_URL == "sqlite:///./data/dobedub-studio.db"
    assert start.PID_FILE == stop.PID_FILE
    assert start.LOG_FILE.name == "local-server.log"


def _load_script(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    if name == "run_local":
        module.uvicorn = types.SimpleNamespace(run=lambda *_args, **_kwargs: None)
    spec.loader.exec_module(module)
    return module
