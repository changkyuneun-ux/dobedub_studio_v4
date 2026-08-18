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
    sandbox_pod_graphql_url: str = "https://api.runpod.io/graphql"
    sandbox_pod_graphql_api_key: str = ""
    sandbox_pod_timeout: int = 20
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
    auth_jwt_secret: str = "dobedub-studio-local-dev-secret"
    auth_token_ttl_minutes: int = 480
    task_monitor_interval_seconds: int = 5
    observability_enabled: bool = True
    observability_environment: str = "local"
    observability_slow_request_ms: int = 500


def get_settings() -> Settings:
    # B-04: 환경변수가 아예 없을 때의 폴백을 실제 실행("0")으로 통일한다 - 운영
    # 배포는 항상 RUNPOD_DRY_RUN=0을 명시하므로 이것이 실제 운영 기본값이다.
    # RUNPOD_API_KEY/RUNPOD_ENDPOINT_ID가 없는 미설정 환경에서는 dry-run으로
    # 조용히 넘어가는 대신 runpod_client.runpod_headers()가 ValueError로 즉시
    # 실패해 잘못된 설정을 드러낸다. 로컬 개발에서 안전한 시뮬레이션이 필요하면
    # .env.example처럼 RUNPOD_DRY_RUN=1을 명시적으로 설정한다.
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
        auth_token_ttl_minutes = int(os.environ.get("AUTH_TOKEN_TTL_MINUTES", "480"))
    except ValueError:
        auth_token_ttl_minutes = 480
    try:
        task_monitor_interval_seconds = min(60, max(1, int(os.environ.get("TASK_MONITOR_INTERVAL_SECONDS", "5"))))
    except ValueError:
        task_monitor_interval_seconds = 5
    try:
        observability_slow_request_ms = min(60_000, max(1, int(os.environ.get("OBSERVABILITY_SLOW_REQUEST_MS", "500"))))
    except ValueError:
        observability_slow_request_ms = 500
    return Settings(
        workflow_seed_dir=Path(os.environ.get("WORKFLOW_SEED_DIR", PROJECT_ROOT / "workflows")),
        workflows_dir=Path(os.environ.get("WORKFLOWS_DIR", PROJECT_ROOT / "workflows")),
        data_dir=Path(os.environ.get("STUDIO_DATA_DIR", PROJECT_ROOT / "data")),
        metadata_dir=Path(os.environ.get("METADATA_DIR", PROJECT_ROOT / "metadata")),
        persistence_backend=os.environ.get("PERSISTENCE_BACKEND", "json").strip().lower() or "json",
        database_url=os.environ.get("DATABASE_URL", "sqlite:///./data/dobedub-studio.db"),
        database_echo=os.environ.get("DATABASE_ECHO", "0") in {"1", "true", "TRUE", "yes", "YES"},
        database_ssl_ca=os.environ.get("DATABASE_SSL_CA", ""),
        database_ssl_verify_identity=os.environ.get("DATABASE_SSL_VERIFY_IDENTITY", "0") in {"1", "true", "TRUE", "yes", "YES"},
        storage_backend=os.environ.get("STORAGE_BACKEND", "local"),
        s3_bucket=os.environ.get("S3_BUCKET", ""),
        s3_prefix=os.environ.get("S3_PREFIX", "dobedub-studio"),
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
        sandbox_pod_graphql_url=os.environ.get("RUNPOD_SANDBOX_POD_GRAPHQL_URL", "https://api.runpod.io/graphql"),
        sandbox_pod_graphql_api_key=os.environ.get("RUNPOD_SANDBOX_POD_GRAPHQL_API_KEY", ""),
        sandbox_pod_timeout=sandbox_pod_timeout,
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
        auth_jwt_secret=os.environ.get("AUTH_JWT_SECRET", "dobedub-studio-local-dev-secret"),
        auth_token_ttl_minutes=auth_token_ttl_minutes,
        task_monitor_interval_seconds=task_monitor_interval_seconds,
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
