from backend.app.db.models import WorkflowTask
from backend.app.services.task_tracking_service import task_history_items


def test_task_history_exposes_runpod_generation_from_status_json(db_session):
    task = WorkflowTask(
        id="task_generation_history",
        workflow_id="wan22_default_81.json",
        status="COMPLETED",
        progress=100,
        worker_name="operator",
        payload_json={},
        config_json={"frames": 81, "fps": 16},
        runpod_status_json={
            "status": "COMPLETED",
            "generation": [
                {
                    "nodeId": "98",
                    "width": 848,
                    "height": 480,
                    "length": 81,
                    "pixelCount": 407040,
                }
            ],
        },
    )
    db_session.add(task)
    db_session.commit()

    item = task_history_items(1, 10)[0]

    assert item["runpodGeneration"] == [
        {
            "nodeId": "98",
            "width": 848,
            "height": 480,
            "length": 81,
            "pixelCount": 407040,
        }
    ]
    assert item["runpodResponse"]["generation"] == item["runpodGeneration"]


def test_task_history_preserves_requested_generation_when_provider_generation_is_missing(db_session):
    requested = [{"nodeId": "98", "width": 464, "height": 864, "length": 81, "tier": "sd"}]
    db_session.add(WorkflowTask(
        id="task_requested_generation_history",
        workflow_id="wan22_default_81.json",
        status="COMPLETED",
        progress=100,
        worker_name="operator",
        payload_json={},
        config_json={"frames": 81, "fps": 16},
        patch_summary={"generation": requested},
        runpod_status_json={"status": "COMPLETED"},
    ))
    db_session.commit()

    item = next(item for item in task_history_items(1, 10) if item["taskId"] == "task_requested_generation_history")

    assert item["requestedGeneration"] == requested
    assert item["runpodGeneration"] == []
