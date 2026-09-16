from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[3]


@dataclass(frozen=True)
class Settings:
    app_name: str = "DOBEDUB STUDIO API"
    api_prefix: str = "/api/v1"
    project_root: Path = PROJECT_ROOT
    workflow_seed_dir: Path = PROJECT_ROOT / "workflows"
    workflows_dir: Path = PROJECT_ROOT / "workflows"
    data_dir: Path = PROJECT_ROOT / "data"
    metadata_dir: Path = PROJECT_ROOT / "metadata"
    persistence_backend: str = "json"
    database_url: str = "sqlite:///./data/dobedub-studio.db"
    database_echo: bool = False
    database_ssl_ca: str = ""
    database_ssl_verify_identity: bool = False
    storage_backend: str = "local"
    s3_bucket: str = ""
    s3_prefix: str = "dobedub-studio"
    s3_endpoint_url: str = ""
    s3_force_path_style: bool = False
    # B-04: 운영 배포 문서(ecs-express-deployment-runbook.md 외 3곳)가 모두
    # RUNPOD_DRY_RUN=0(실제 실행)을 운영 환경 필수값으로 명시하므로, 코드 기본값도
    # 실제 운영 기본값에 맞춘다. 로컬 개발은 .env.example의 명시적
    # RUNPOD_DRY_RUN=1로 안전하게 유지된다.
    dry_run: bool = False
    runpod_api_key: str = ""
    runpod_endpoint_id: str = ""
    runpod_base_url: str = "https://api.runpod.ai/v2"
    runpod_timeout: int = 30
    sandbox_pod_id: str = ""
    sandbox_pod_name: str = ""
    sandbox_pod_network_volume_id: str = ""
    sandbox_pod_template_id: str = ""
    sandbox_pod_gpu_type_id: str = ""
    sandbox_pod_gpu_count: int = 1
    sandbox_pod_deploy_name: str = "dobedub_comfyUI_Sandbox"
    sandbox_pod_api_key: str = ""
    sandbox_pod_rest_url: str = "https://rest.runpod.io/v1"
    # REST v2 is read-only here: live runtime metrics and the GPU catalog, which v1 does not
    # expose. 2026-09-14: v2 lives on a DIFFERENT HOST than v1 (api.runpod.io, not
    # rest.runpod.io) — the previous default pointed at rest.runpod.io/v2, which doesn't exist
    # and 302-redirects to RunPod's docs site, so every catalog/runtime-metrics call silently
    # failed (caught by the bare except in _fetch_gpu_catalog / _runtime_metrics) and the admin
    # screen's VRAM/재고/live-metrics columns stayed blank with no error. Confirmed against
    # RunPod's own docs (docs.runpod.io/api-reference-v2/{catalog/list-gpu-types,pods/get-a-pod}).
    sandbox_pod_rest_v2_url: str = "https://api.runpod.io/v2"
    sandbox_pod_timeout: int = 20
    # Multi-pod / GPU fallback (spec 2026-09-11 §5.1). Empty fallback list
    # keeps the legacy single-GPU create behaviour.
    sandbox_pod_gpu_fallback_type_ids: tuple[str, ...] = ()
    sandbox_pod_start_retry_count: int = 1
    sandbox_pod_create_attempt_delay_seconds: float = 2.0
    sandbox_pod_min_vram_gb: int = 24
    sandbox_pod_stop_wait_seconds: int = 60
    prompt_llm_provider: str = "mock"
    prompt_llm_api_key: str = ""
    prompt_llm_endpoint_id: str = ""
    prompt_llm_endpoint_url: str = ""
    prompt_llm_model: str = ""
    prompt_llm_runpod_input_mode: str = "prompt"
    prompt_llm_temperature: float = 0.2
    prompt_llm_max_tokens: int = 900
    prompt_llm_timeout: int = 45
    prompt_llm_cold_start_retry_delays_seconds: tuple[int, ...] = (5, 10, 20, 30, 30)
    prompt_llm_runpod_execution_mode: str = "async"
    prompt_llm_submit_timeout: int = 20
    prompt_llm_cold_start_timeout: int = 900
    prompt_llm_poll_interval: int = 3
    # Grok Vision is intentionally isolated from the legacy Qwen/RunPod
    # prompt path. It generates a per-upload positive prompt only.
    grok_enabled: bool = False
    grok_api_key: str = ""
    grok_base_url: str = "https://api.x.ai/v1"
    grok_model: str = "grok-4-1-fast-reasoning"
    grok_auto_generate_on_upload: bool = False
    grok_max_image_bytes: int = 20 * 1024 * 1024
    grok_max_output_tokens: int = 600
    grok_temperature: float = 0.2
    grok_request_timeout_seconds: int = 120
    grok_max_retries: int = 2
    grok_retry_backoff_seconds: float = 2.0
    grok_instruction_set_path: Path = PROJECT_ROOT / "data" / "grok_instruction_set.json"
    auth_jwt_secret: str = "dobedub-studio-local-dev-secret"
    auth_token_ttl_minutes: int = 480
    task_monitor_interval_seconds: int = 5
    webtoon_cut_monitor_interval_seconds: int = 1
    observability_enabled: bool = True
    observability_environment: str = "local"
    observability_slow_request_ms: int = 500


def get_settings() -> Settings:
    # RUNPOD_DRY_RUN은 기존 환경 파일과 health 응답의 호환을 위해 읽기만
    # 한다. 배치 디스패처는 이 값과 무관하게 실제 /health와 /run을 호출한다.
    # 테스트는 JobRuntime의 runpod_request 더블로 네트워크를 차단한다.
    dry_run = os.environ.get("RUNPOD_DRY_RUN", "0") != "0"
    try:
        runpod_timeout = int(os.environ.get("RUNPOD_TIMEOUT", "30"))
    except ValueError:
        runpod_timeout = 30
    try:
        sandbox_pod_timeout = int(os.environ.get("RUNPOD_SANDBOX_POD_TIMEOUT", "20"))
    except ValueError:
        sandbox_pod_timeout = 20
    try:
        sandbox_pod_gpu_count = max(1, int(os.environ.get("RUNPOD_SANDBOX_GPU_COUNT", "1")))
    except ValueError:
        sandbox_pod_gpu_count = 1
    sandbox_pod_gpu_fallback_type_ids = tuple(
        item.strip()
        for item in os.environ.get("RUNPOD_SANDBOX_GPU_FALLBACK_TYPE_IDS", "").split(",")
        if item.strip()
    )
    try:
        sandbox_pod_start_retry_count = max(0, int(os.environ.get("RUNPOD_SANDBOX_START_RETRY_COUNT", "1")))
    except ValueError:
        sandbox_pod_start_retry_count = 1
    try:
        sandbox_pod_create_attempt_delay_seconds = max(
            0.0, float(os.environ.get("RUNPOD_SANDBOX_CREATE_ATTEMPT_DELAY_SECONDS", "2"))
        )
    except ValueError:
        sandbox_pod_create_attempt_delay_seconds = 2.0
    try:
        sandbox_pod_min_vram_gb = max(0, int(os.environ.get("RUNPOD_SANDBOX_MIN_VRAM_GB", "24")))
    except ValueError:
        sandbox_pod_min_vram_gb = 24
    try:
        sandbox_pod_stop_wait_seconds = max(0, int(os.environ.get("RUNPOD_SANDBOX_STOP_WAIT_SECONDS", "60")))
    except ValueError:
        sandbox_pod_stop_wait_seconds = 60
    try:
        prompt_llm_timeout = int(os.environ.get("PROMPT_LLM_TIMEOUT", "45"))
    except ValueError:
        prompt_llm_timeout = 45
    prompt_llm_cold_start_retry_delays_seconds = _prompt_llm_retry_delays(
        os.environ.get("PROMPT_LLM_COLD_START_RETRY_DELAYS_SECONDS", "5,10,20,30,30")
    )
    prompt_llm_runpod_execution_mode = os.environ.get("PROMPT_LLM_RUNPOD_EXECUTION_MODE", "async").strip().lower() or "async"
    if prompt_llm_runpod_execution_mode not in {"async", "sync"}:
        prompt_llm_runpod_execution_mode = "async"
    try:
        prompt_llm_submit_timeout = min(120, max(5, int(os.environ.get("PROMPT_LLM_SUBMIT_TIMEOUT", "20"))))
    except ValueError:
        prompt_llm_submit_timeout = 20
    try:
        prompt_llm_cold_start_timeout = min(3600, max(60, int(os.environ.get("PROMPT_LLM_COLD_START_TIMEOUT", "900"))))
    except ValueError:
        prompt_llm_cold_start_timeout = 900
    try:
        prompt_llm_poll_interval = min(30, max(1, int(os.environ.get("PROMPT_LLM_POLL_INTERVAL", "3"))))
    except ValueError:
        prompt_llm_poll_interval = 3
    try:
        prompt_llm_temperature = float(os.environ.get("PROMPT_LLM_TEMPERATURE", "0.2"))
    except ValueError:
        prompt_llm_temperature = 0.2
    try:
        prompt_llm_max_tokens = int(os.environ.get("PROMPT_LLM_MAX_TOKENS", "900"))
    except ValueError:
        prompt_llm_max_tokens = 900
    try:
        grok_max_image_bytes = min(50 * 1024 * 1024, max(256 * 1024, int(os.environ.get("GROK_MAX_IMAGE_BYTES", str(20 * 1024 * 1024)))))
    except ValueError:
        grok_max_image_bytes = 20 * 1024 * 1024
    try:
        grok_max_output_tokens = min(2_000, max(64, int(os.environ.get("GROK_MAX_OUTPUT_TOKENS", "600"))))
    except ValueError:
        grok_max_output_tokens = 600
    try:
        grok_temperature = min(1.0, max(0.0, float(os.environ.get("GROK_TEMPERATURE", "0.2"))))
    except ValueError:
        grok_temperature = 0.2
    try:
        grok_request_timeout_seconds = min(300, max(10, int(os.environ.get("GROK_REQUEST_TIMEOUT_SECONDS", "120"))))
    except ValueError:
        grok_request_timeout_seconds = 120
    try:
        grok_max_retries = min(5, max(0, int(os.environ.get("GROK_MAX_RETRIES", "2"))))
    except ValueError:
        grok_max_retries = 2
    try:
        grok_retry_backoff_seconds = min(30.0, max(0.25, float(os.environ.get("GROK_RETRY_BACKOFF_SECONDS", "2"))))
    except ValueError:
        grok_retry_backoff_seconds = 2.0
    try:
        auth_token_ttl_minutes = int(os.environ.get("AUTH_TOKEN_TTL_MINUTES", "480"))
    except ValueError:
        auth_token_ttl_minutes = 480
    try:
        task_monitor_interval_seconds = min(60, max(1, int(os.environ.get("TASK_MONITOR_INTERVAL_SECONDS", "5"))))
    except ValueError:
        task_monitor_interval_seconds = 5
    try:
        webtoon_cut_monitor_interval_seconds = min(10, max(1, int(os.environ.get("WEBTOON_CUT_MONITOR_INTERVAL_SECONDS", "1"))))
    except ValueError:
        webtoon_cut_monitor_interval_seconds = 1
    try:
        observability_slow_request_ms = min(60_000, max(1, int(os.environ.get("OBSERVABILITY_SLOW_REQUEST_MS", "500"))))
    except ValueError:
        observability_slow_request_ms = 500
    data_dir = Path(os.environ.get("STUDIO_DATA_DIR", PROJECT_ROOT / "data"))
    return Settings(
        workflow_seed_dir=Path(os.environ.get("WORKFLOW_SEED_DIR", PROJECT_ROOT / "workflows")),
        workflows_dir=Path(os.environ.get("WORKFLOWS_DIR", PROJECT_ROOT / "workflows")),
        data_dir=data_dir,
        metadata_dir=Path(os.environ.get("METADATA_DIR", PROJECT_ROOT / "metadata")),
        persistence_backend=os.environ.get("PERSISTENCE_BACKEND", "json").strip().lower() or "json",
        database_url=os.environ.get("DATABASE_URL", "sqlite:///./data/dobedub-studio.db"),
        database_echo=os.environ.get("DATABASE_ECHO", "0") in {"1", "true", "TRUE", "yes", "YES"},
        database_ssl_ca=os.environ.get("DATABASE_SSL_CA", ""),
        database_ssl_verify_identity=os.environ.get("DATABASE_SSL_VERIFY_IDENTITY", "0") in {"1", "true", "TRUE", "yes", "YES"},
        storage_backend=os.environ.get("STORAGE_BACKEND", "local"),
        s3_bucket=os.environ.get("S3_BUCKET", ""),
        s3_prefix=os.environ.get("S3_PREFIX", "dobedub-studio"),
        s3_endpoint_url=os.environ.get("S3_ENDPOINT_URL", "").strip(),
        s3_force_path_style=os.environ.get("S3_FORCE_PATH_STYLE", "0") in {"1", "true", "TRUE", "yes", "YES"},
        dry_run=dry_run,
        runpod_api_key=os.environ.get("RUNPOD_API_KEY", ""),
        runpod_endpoint_id=os.environ.get("RUNPOD_ENDPOINT_ID", ""),
        runpod_base_url=os.environ.get("RUNPOD_BASE_URL", "https://api.runpod.ai/v2"),
        runpod_timeout=runpod_timeout,
        sandbox_pod_id=os.environ.get("RUNPOD_SANDBOX_POD_ID", ""),
        sandbox_pod_name=os.environ.get("RUNPOD_SANDBOX_POD_NAME", ""),
        sandbox_pod_network_volume_id=os.environ.get("RUNPOD_SANDBOX_NETWORK_VOLUME_ID", ""),
        sandbox_pod_template_id=os.environ.get("RUNPOD_SANDBOX_TEMPLATE_ID", ""),
        sandbox_pod_gpu_type_id=os.environ.get("RUNPOD_SANDBOX_GPU_TYPE_ID", ""),
        sandbox_pod_gpu_count=sandbox_pod_gpu_count,
        sandbox_pod_deploy_name=os.environ.get("RUNPOD_SANDBOX_DEPLOY_NAME", "dobedub_comfyUI_Sandbox"),
        sandbox_pod_api_key=os.environ.get("RUNPOD_SANDBOX_POD_API_KEY", ""),
        sandbox_pod_rest_url=os.environ.get("RUNPOD_SANDBOX_POD_REST_URL", "https://rest.runpod.io/v1"),
        sandbox_pod_rest_v2_url=os.environ.get("RUNPOD_SANDBOX_POD_REST_V2_URL", "https://api.runpod.io/v2"),
        sandbox_pod_timeout=sandbox_pod_timeout,
        sandbox_pod_gpu_fallback_type_ids=sandbox_pod_gpu_fallback_type_ids,
        sandbox_pod_start_retry_count=sandbox_pod_start_retry_count,
        sandbox_pod_create_attempt_delay_seconds=sandbox_pod_create_attempt_delay_seconds,
        sandbox_pod_min_vram_gb=sandbox_pod_min_vram_gb,
        sandbox_pod_stop_wait_seconds=sandbox_pod_stop_wait_seconds,
        prompt_llm_provider=os.environ.get("PROMPT_LLM_PROVIDER", "mock").strip().lower() or "mock",
        prompt_llm_api_key=os.environ.get("PROMPT_LLM_API_KEY", ""),
        prompt_llm_endpoint_id=os.environ.get("PROMPT_LLM_ENDPOINT_ID", ""),
        prompt_llm_endpoint_url=os.environ.get("PROMPT_LLM_ENDPOINT_URL", ""),
        prompt_llm_model=os.environ.get("PROMPT_LLM_MODEL", ""),
        prompt_llm_runpod_input_mode=os.environ.get("PROMPT_LLM_RUNPOD_INPUT_MODE", "prompt").strip().lower() or "prompt",
        prompt_llm_temperature=prompt_llm_temperature,
        prompt_llm_max_tokens=prompt_llm_max_tokens,
        prompt_llm_timeout=prompt_llm_timeout,
        prompt_llm_cold_start_retry_delays_seconds=prompt_llm_cold_start_retry_delays_seconds,
        prompt_llm_runpod_execution_mode=prompt_llm_runpod_execution_mode,
        prompt_llm_submit_timeout=prompt_llm_submit_timeout,
        prompt_llm_cold_start_timeout=prompt_llm_cold_start_timeout,
        prompt_llm_poll_interval=prompt_llm_poll_interval,
        grok_enabled=os.environ.get("GROK_ENABLED", "0") in {"1", "true", "TRUE", "yes", "YES"},
        grok_api_key=os.environ.get("GROK_API_KEY", ""),
        grok_base_url=os.environ.get("GROK_BASE_URL", "https://api.x.ai/v1").rstrip("/"),
        grok_model=os.environ.get("GROK_MODEL", "grok-4-1-fast-reasoning").strip() or "grok-4-1-fast-reasoning",
        grok_auto_generate_on_upload=os.environ.get("GROK_AUTO_GENERATE_ON_UPLOAD", "0") not in {"0", "false", "FALSE", "no", "NO"},
        grok_max_image_bytes=grok_max_image_bytes,
        grok_max_output_tokens=grok_max_output_tokens,
        grok_temperature=grok_temperature,
        grok_request_timeout_seconds=grok_request_timeout_seconds,
        grok_max_retries=grok_max_retries,
        grok_retry_backoff_seconds=grok_retry_backoff_seconds,
        grok_instruction_set_path=Path(os.environ.get("GROK_INSTRUCTION_SET_PATH", data_dir / "grok_instruction_set.json")),
        auth_jwt_secret=os.environ.get("AUTH_JWT_SECRET", "dobedub-studio-local-dev-secret"),
        auth_token_ttl_minutes=auth_token_ttl_minutes,
        task_monitor_interval_seconds=task_monitor_interval_seconds,
        webtoon_cut_monitor_interval_seconds=webtoon_cut_monitor_interval_seconds,
        observability_enabled=os.environ.get("OBSERVABILITY_ENABLED", "1") not in {"0", "false", "FALSE", "no", "NO"},
        observability_environment=os.environ.get("OBSERVABILITY_ENVIRONMENT", "local").strip() or "local",
        observability_slow_request_ms=observability_slow_request_ms,
    )


def _prompt_llm_retry_delays(raw_value: str) -> tuple[int, ...]:
    delays: list[int] = []
    for value in raw_value.split(","):
        try:
            delay = int(value.strip())
        except ValueError:
            continue
        if 1 <= delay <= 120:
            delays.append(delay)
    return tuple(delays[:8]) or (5, 10, 20, 30, 30)
