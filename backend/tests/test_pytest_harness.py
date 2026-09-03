from __future__ import annotations

from backend.app.db.models import WorkflowTask


def test_db_session_fixture_creates_schema(db_session):
    task = WorkflowTask(
        id="task_fixture_1",
        workflow_id="1-images.json",
        status="COMPLETED",
    )
    db_session.add(task)
    db_session.commit()

    assert db_session.get(WorkflowTask, "task_fixture_1").workflow_id == "1-images.json"


def test_fake_runpod_records_calls(fake_runpod):
    assert fake_runpod("POST", "/run", {"input": {}}) == {"id": "runpod_job_test_1"}
    assert fake_runpod.calls == [("POST", "/run", {"input": {}})]
