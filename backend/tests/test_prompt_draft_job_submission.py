from __future__ import annotations

from pathlib import Path

from backend.app.db.models import Asset, ImagePromptDraft
from backend.app.services import studio_api_service, workflow_patch_service


def test_draft_job_payload_uses_the_draft_prompt_for_fixed_81_workflow(db_session):
    db_session.add(Asset(
        id="asset_for_job",
        asset_type="input",
        file_name="source.png",
        mime_type="image/png",
        size_bytes=1,
        image_width=720,
        image_height=1280,
        storage_key="inputs/source.png",
        metadata_json={},
    ))
    db_session.add(ImagePromptDraft(
        id="grok_draft_job",
        asset_id="asset_for_job",
        workflow_id="1-images_81.json",
        slot_index=1,
        status="READY",
        provider="grok",
        model="grok-test",
        instruction_version="wf@1",
        positive_prompt="a person walks forward",
        negative_prompt="blur",
        requested_frames=81,
        warnings_json=[],
        raw_json={},
        created_by="dobedub",
    ))
    db_session.commit()

    payload = studio_api_service.job_payload_from_prompt_draft("grok_draft_job", user={"id": "dobedub", "name": "Dob"})

    assert payload["promptDraftId"] == "grok_draft_job"
    assert payload["workflowId"] == "1-images_81.json"
    assert payload["workflowName"] == "1-images_81"
    assert payload["keyframes"] == [{"index": 1, "uploadId": "asset_for_job", "fileName": "source.png"}]
    assert payload["segments"][0]["positivePrompt"] == "a person walks forward"
    assert payload["segments"][0]["negativePromptAddition"] == "blur"
    assert payload["segments"][0]["config"]["frames"] == 81
    assert payload["segments"][0]["config"]["duration_seconds"] == 5
    assert payload["segments"][0]["config"]["duration"] == 5
    assert payload["segments"][0]["config"]["fps"] == 16
    assert payload["segments"][0]["config"]["output_fps"] == 16
    assert payload["segments"][0]["config"]["width"] == 720
    assert payload["segments"][0]["config"]["height"] == 1280

    workflow = {"98": {"inputs": {"length": 81}}}
    applied = workflow_patch_service.apply_node_config_to_workflow(
        workflow,
        payload["workflowId"],
        payload["segments"],
        Path("workflows"),
    )

    assert applied == []
    assert workflow["98"]["inputs"]["length"] == 81
