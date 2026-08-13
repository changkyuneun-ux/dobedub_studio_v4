from __future__ import annotations

import json
import mimetypes
import re
import threading
import uuid
from datetime import datetime
from pathlib import Path

from backend.app.services.asset_storage import (
    asset_record,
    decode_data_url,
    image_dimensions,
    media_kind,
    path_within_storage,
    safe_filename,
)


WRITE_JSON_LOCK = threading.Lock()


def read_json(path: Path):
    with path.open("r", encoding="utf-8") as stream:
        return json.load(stream)


def write_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")
    with WRITE_JSON_LOCK:
        try:
            with tmp.open("w", encoding="utf-8") as stream:
                json.dump(value, stream, ensure_ascii=False, indent=2)
            tmp.replace(path)
        finally:
            if tmp.exists():
                tmp.unlink()


def hydrate_output_asset(asset: dict, assets: dict | None = None, assets_path: Path | None = None) -> dict:
    assets = assets if assets is not None else load_assets(assets_path)
    item = dict(asset or {})
    stored = assets.get(item.get("assetId"), {})
    file_name = item.get("fileName") or item.get("filename") or stored.get("fileName") or "generated-output"
    mime_type = (
        item.get("mimeType")
        or stored.get("mimeType")
        or mimetypes.guess_type(file_name)[0]
        or "application/octet-stream"
    )
    item.update({
        "fileName": file_name,
        "kind": media_kind(file_name, mime_type, item.get("kind")),
        "mimeType": mime_type,
        "downloadUrl": item.get("downloadUrl") or item.get("url") or f"/api/files/{item.get('assetId')}",
        "sizeBytes": item.get("sizeBytes") or stored.get("sizeBytes"),
    })
    return item


def prompt_list_from_pipe(value) -> list[dict]:
    text = str(value or "").strip()
    if not text:
        return []
    parts = [part.strip() for part in text.split("|") if part.strip()]
    result = []
    for index, part in enumerate(parts, start=1):
        cleaned = re.sub(r"^\s*\d+\s*[:.)-]\s*", "", part).strip()
        if cleaned:
            result.append({"index": index, "text": cleaned})
    return result or [{"index": 1, "text": text}]


def history_prompt_items(item: dict, field: str, fallback: str = "") -> list[dict]:
    stored = item.get(f"{field}Prompts")
    if isinstance(stored, list) and stored:
        result = []
        for index, value in enumerate(stored, start=1):
            if isinstance(value, dict):
                text = value.get("text") or value.get(field) or value.get("prompt") or ""
                prompt_index = value.get("index") or index
            else:
                text = value
                prompt_index = index
            if str(text or "").strip():
                result.append({"index": prompt_index, "text": str(text).strip()})
        if result:
            return result
    segments = item.get("segments") or []
    segment_key = "positivePrompt" if field == "positive" else "negativePromptAddition"
    result = [
        {"index": segment.get("index") or index + 1, "text": str(segment.get(segment_key) or "").strip()}
        for index, segment in enumerate(segments)
        if str(segment.get(segment_key) or "").strip()
    ]
    if result:
        return result
    return prompt_list_from_pipe(item.get(f"{field}Prompt") or fallback)


def hydrate_input_images(item: dict, assets: dict | None = None, assets_path: Path | None = None) -> list[dict]:
    assets = assets if assets is not None else load_assets(assets_path)
    keyframes = item.get("keyframes") or []
    input_assets = item.get("inputAssets") or []
    result = []
    seen = set()
    for index, keyframe in enumerate(keyframes, start=1):
        asset_id = keyframe.get("uploadId") or (input_assets[index - 1] if index - 1 < len(input_assets) else "")
        stored = assets.get(asset_id, {}) if asset_id else {}
        file_name = keyframe.get("fileName") or stored.get("fileName") or "-"
        if asset_id or file_name != "-":
            key = (asset_id, file_name)
            if key not in seen:
                result.append({
                    "index": keyframe.get("index") or index,
                    "assetId": asset_id,
                    "fileName": file_name,
                    "sizeBytes": keyframe.get("sizeBytes") or stored.get("sizeBytes"),
                    "imageWidth": keyframe.get("imageWidth") or stored.get("imageWidth"),
                    "imageHeight": keyframe.get("imageHeight") or stored.get("imageHeight"),
                })
                seen.add(key)
    for index, asset_id in enumerate(input_assets, start=1):
        if any(item.get("assetId") == asset_id for item in result):
            continue
        stored = assets.get(asset_id, {})
        result.append({
            "index": index,
            "assetId": asset_id,
            "fileName": stored.get("fileName") or "-",
            "sizeBytes": stored.get("sizeBytes"),
            "imageWidth": stored.get("imageWidth"),
            "imageHeight": stored.get("imageHeight"),
        })
    return result


def hydrate_history_item(item: dict, assets: dict | None = None, assets_path: Path | None = None) -> dict:
    hydrated = dict(item or {})
    hydrated["outputAssets"] = [
        hydrate_output_asset(asset, assets, assets_path)
        for asset in hydrated.get("outputAssets") or []
    ]
    user = hydrated.get("user") or {}
    hydrated["workerName"] = hydrated.get("workerName") or user.get("name") or hydrated.get("userName") or "-"
    hydrated["positivePrompts"] = history_prompt_items(hydrated, "positive", hydrated.get("prompt", ""))
    hydrated["negativePrompts"] = history_prompt_items(hydrated, "negative", hydrated.get("negativePrompt", ""))
    hydrated["inputImages"] = hydrated.get("inputImages") or hydrate_input_images(hydrated, assets, assets_path)
    hydrated["wanNodeConfig"] = hydrated.get("wanNodeConfig") or {}
    return hydrated


def load_assets(assets_path: Path | None) -> dict:
    if not assets_path or not assets_path.exists():
        return {}
    return read_json(assets_path)


def save_assets(assets_path: Path, assets: dict):
    write_json(assets_path, assets)


# D-03: task history storage is DB-only in production. This function is no
# longer reachable from the live app (studio_api_service always uses
# history_repository(), which is DB-backed) and is retained only for the
# legacy-data path exercised by scripts/migrate_json_to_db.py and by tests
# of the JSON adapter itself. Do not wire new history reads through this.
def load_history(history_path: Path, assets_path: Path) -> list[dict]:
    if not history_path.exists():
        return []
    assets = load_assets(assets_path)
    return [hydrate_history_item(item, assets, assets_path) for item in read_json(history_path)]


# D-03: legacy/migration-tool-only, see load_history() above.
def raw_history_items(history_path: Path) -> list[dict]:
    if not history_path.exists():
        return []
    return read_json(history_path)


# D-03: legacy/migration-tool-only, see load_history() above.
def append_history(history_path: Path, assets_path: Path, item: dict) -> list[dict]:
    history = load_history(history_path, assets_path)
    history.insert(0, item)
    write_json(history_path, history[:200])
    return history


def load_configs(configs_path: Path) -> list[dict]:
    if not configs_path.exists():
        return []
    return read_json(configs_path)


def append_config(configs_path: Path, item: dict) -> list[dict]:
    configs = load_configs(configs_path)
    configs.insert(0, item)
    write_json(configs_path, configs[:200])
    return configs


def item_asset_ids(item: dict) -> list[str]:
    asset_ids = []

    def add(value):
        text = str(value or "").strip()
        if text and text not in asset_ids:
            asset_ids.append(text)

    for asset_id in item.get("inputAssets") or []:
        add(asset_id)
    for image in item.get("inputImages") or []:
        if isinstance(image, dict):
            add(image.get("assetId"))
    for keyframe in item.get("keyframes") or []:
        if isinstance(keyframe, dict):
            add(keyframe.get("uploadId"))
    for asset in item.get("outputAssets") or []:
        if isinstance(asset, dict):
            add(asset.get("assetId"))
    return asset_ids


def delete_asset_file(asset: dict, uploads_dir: Path, outputs_dir: Path) -> dict:
    path = asset.get("path")
    if not path or not path_within_storage(path, [uploads_dir, outputs_dir]):
        return {"path": path or "", "deleted": False, "reason": "not-managed-path"}
    file_path = Path(path)
    if not file_path.exists():
        return {"path": str(file_path), "deleted": False, "reason": "missing"}
    file_path.unlink()
    return {"path": str(file_path), "deleted": True, "reason": ""}


# D-03: legacy/migration-tool-only, see load_history() above.
def delete_history_item(history_path: Path, assets_path: Path, uploads_dir: Path, outputs_dir: Path, task_id: str) -> dict:
    history = raw_history_items(history_path)
    target_index = next((index for index, item in enumerate(history) if item.get("taskId") == task_id), None)
    if target_index is None:
        raise KeyError(task_id)

    item = history.pop(target_index)
    assets = load_assets(assets_path)
    removed_assets = []
    file_results = []

    for asset_id in item_asset_ids(item):
        asset = assets.pop(asset_id, None)
        if not asset:
            file_results.append({"assetId": asset_id, "path": "", "deleted": False, "reason": "asset-metadata-missing"})
            continue
        result = delete_asset_file(asset, uploads_dir, outputs_dir)
        result["assetId"] = asset_id
        file_results.append(result)
        removed_assets.append(asset_id)

    write_json(history_path, history)
    save_assets(assets_path, assets)
    return {
        "deleted": True,
        "taskId": task_id,
        "removedAssets": removed_assets,
        "fileResults": file_results,
    }


def register_asset(assets_path: Path, file_path: Path, asset_type: str, mime_type: str | None = None, file_name: str | None = None) -> dict:
    item = asset_record(file_path, asset_type, mime_type, file_name)
    assets = load_assets(assets_path)
    assets[item["assetId"]] = item
    save_assets(assets_path, assets)
    return item


def create_upload(assets_path: Path, uploads_dir: Path, payload: dict) -> dict:
    file_name = safe_filename(payload.get("fileName"))
    raw, mime_type = decode_data_url(payload.get("dataUrl", ""))
    if len(raw) == 0:
        raise ValueError("uploaded file is empty")
    asset_id = f"asset_{uuid.uuid4().hex[:12]}"
    stored_name = f"{asset_id}_{file_name}"
    path = uploads_dir / stored_name
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as stream:
        stream.write(raw)

    item = {
        "assetId": asset_id,
        "type": "input_image",
        "fileName": file_name,
        "mimeType": payload.get("mimeType") or mime_type,
        "sizeBytes": len(raw),
        "path": str(path),
        "createdAt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    image_width, image_height = image_dimensions(raw, item["mimeType"])
    if image_width and image_height:
        item["imageWidth"] = image_width
        item["imageHeight"] = image_height
    assets = load_assets(assets_path)
    assets[asset_id] = item
    save_assets(assets_path, assets)
    return item


def get_asset(assets_path: Path, asset_id: str) -> tuple[dict, Path]:
    asset = load_assets(assets_path).get(asset_id)
    if not asset:
        raise KeyError(asset_id)
    path = Path(asset.get("path", ""))
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(asset_id)
    return asset, path
