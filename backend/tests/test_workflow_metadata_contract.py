from pathlib import Path


def test_runtime_has_no_hardcoded_allowlist_or_legacy_registry_dependency():
    files = list(Path("backend/app").rglob("*.py"))
    occurrences: dict[str, list[str]] = {"SUPPORTED_WORKFLOW_IDS": [], "workflow-registry.json": []}
    for path in files:
        source = path.read_text(encoding="utf-8")
        for token in occurrences:
            if token in source:
                occurrences[token].append(path.as_posix())

    assert occurrences["SUPPORTED_WORKFLOW_IDS"] == []
    assert occurrences["workflow-registry.json"] == ["backend/app/services/workflow_import_service.py"]
