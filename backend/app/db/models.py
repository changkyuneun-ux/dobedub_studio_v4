from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.db.base import Base


def now_utc() -> datetime:
    return datetime.utcnow()


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(191), primary_key=True)
    name: Mapped[str] = mapped_column(String(191), nullable=False)
    email: Mapped[str | None] = mapped_column(String(191), nullable=True, index=True)
    role: Mapped[str] = mapped_column(String(64), nullable=False, default="OPERATOR")
    password_hash: Mapped[str | None] = mapped_column(String(512), nullable=True)
    permissions_json: Mapped[list | None] = mapped_column(JSON, nullable=True, default=list)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, onupdate=now_utc, nullable=False)

    tasks: Mapped[list["WorkflowTask"]] = relationship(back_populates="user")
    extra_permissions: Mapped[list["UserPermission"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class Role(Base):
    __tablename__ = "roles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(191), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    level: Mapped[int] = mapped_column(Integer, nullable=False, default=10)
    is_system: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, onupdate=now_utc, nullable=False)

    permissions: Mapped[list["RolePermission"]] = relationship(back_populates="role", cascade="all, delete-orphan")


class Permission(Base):
    __tablename__ = "permissions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    domain: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(191), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_system: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, onupdate=now_utc, nullable=False)

    role_links: Mapped[list["RolePermission"]] = relationship(back_populates="permission", cascade="all, delete-orphan")
    user_links: Mapped[list["UserPermission"]] = relationship(back_populates="permission", cascade="all, delete-orphan")


class RolePermission(Base):
    __tablename__ = "role_permissions"

    role_id: Mapped[int] = mapped_column(Integer, ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True)
    permission_id: Mapped[int] = mapped_column(Integer, ForeignKey("permissions.id", ondelete="CASCADE"), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, nullable=False)

    role: Mapped[Role] = relationship(back_populates="permissions")
    permission: Mapped[Permission] = relationship(back_populates="role_links")


class UserPermission(Base):
    __tablename__ = "user_permissions"

    user_id: Mapped[str] = mapped_column(String(191), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    permission_id: Mapped[int] = mapped_column(Integer, ForeignKey("permissions.id", ondelete="CASCADE"), primary_key=True)
    grant_type: Mapped[str] = mapped_column(String(16), nullable=False, default="ALLOW")
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, nullable=False)

    user: Mapped[User] = relationship(back_populates="extra_permissions")
    permission: Mapped[Permission] = relationship(back_populates="user_links")


class UiPermissionResource(Base):
    __tablename__ = "ui_permission_resources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    resource_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    resource_key: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    label: Mapped[str] = mapped_column(String(191), nullable=False)
    required_permission_code: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    route_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    method: Mapped[str | None] = mapped_column(String(16), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, onupdate=now_utc, nullable=False)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_logs_created_at_id", "created_at", "id"),
        Index("ix_audit_logs_target", "target_type", "target_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # A-04: 로그인 실패 시도처럼 실제 사용자 레코드가 없거나(오타 id) 이후 탈퇴한
    # 사용자의 과거 기록도 보존해야 하므로 users.id에 대한 FK 제약은 걸지 않는다
    # (느슨한 참조 문자열).
    actor_id: Mapped[str | None] = mapped_column(String(191), nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    target_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    target_id: Mapped[str | None] = mapped_column(String(191), nullable=True)
    before_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    after_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, nullable=False)


class Asset(Base):
    __tablename__ = "assets"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    asset_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    file_name: Mapped[str] = mapped_column(String(512), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(191), nullable=False, default="application/octet-stream")
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    storage_backend: Mapped[str] = mapped_column(String(32), nullable=False, default="local")
    storage_key: Mapped[str] = mapped_column(String(1024), nullable=False)
    public_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    metadata_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, nullable=False)


class Collection(Base):
    # A-02: 자산을 묶는 사용자 컬렉션(화면 5c). created_by는 audit_logs.actor_id와
    # 같은 이유로 users.id에 FK를 걸지 않는다(느슨한 참조).
    __tablename__ = "collections"
    __table_args__ = (
        Index("ix_collections_created_by", "created_by"),
        Index("ix_collections_created_at_id", "created_at", "id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(191), nullable=False)
    created_by: Mapped[str | None] = mapped_column(String(191), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, nullable=False)


class CollectionItem(Base):
    # A-02: 컬렉션 ↔ 자산 연결. (collection_id, asset_id) 복합 PK로 중복 담기 방지.
    __tablename__ = "collection_items"
    __table_args__ = (
        Index("ix_collection_items_collection_order", "collection_id", "sort_order"),
    )

    collection_id: Mapped[int] = mapped_column(Integer, ForeignKey("collections.id", ondelete="CASCADE"), primary_key=True)
    asset_id: Mapped[str] = mapped_column(String(64), ForeignKey("assets.id", ondelete="CASCADE"), primary_key=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, nullable=False)


class WorkflowTask(Base):
    __tablename__ = "workflow_tasks"
    __table_args__ = (
        Index("ix_workflow_tasks_created_at_id", "created_at", "id"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    runpod_job_id: Mapped[str | None] = mapped_column(String(191), nullable=True, index=True)
    workflow_id: Mapped[str] = mapped_column(String(191), nullable=False, index=True)
    # B-04: 이 작업이 실제로 생성될 당시 RunPod에 실제 제출됐는지("runpod") 아니면
    # 로컬 시뮬레이션이었는지("dry-run")를 기록하는 감사용 값이다. 사용자가 화면에서
    # 고르는 실행 옵션이 아니라, 서버의 RUNPOD_DRY_RUN 설정(job_service.create_job)이
    # 작업 생성 시점에 그대로 찍히는 스냅샷이다. 컬럼 기본값은 의도적으로 안전한 쪽
    # ("dry-run")을 유지한다 - executionMode 없이 생성되는 레거시/마이그레이션 경로의
    # 레코드를 실제 실행이었다고 잘못 단정하지 않기 위함이며, 서버의 실제 운영
    # 기본값(dry_run=False, get_settings 참조)과는 별개다.
    execution_mode: Mapped[str] = mapped_column(String(32), nullable=False, default="dry-run")
    status: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    worker_name: Mapped[str | None] = mapped_column(String(191), nullable=True)
    user_id: Mapped[str | None] = mapped_column(String(191), ForeignKey("users.id"), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # B-05: 이력 soft delete. NULL이면 살아있는 작업, 값이 있으면 삭제된 것으로 보고
    # 모든 이력 조회(목록·총계·재사용 프롬프트)에서 제외한다. 결과물 파일(assets)은
    # 남긴다(3a "결과물 파일은 Assets에 남습니다").
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    elapsed_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    positive_prompts: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    negative_prompts: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    config_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    wan_node_config: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    patch_summary: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    payload_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    runpod_submit_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    runpod_status_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, onupdate=now_utc, nullable=False)

    user: Mapped[User | None] = relationship(back_populates="tasks")
    input_assets: Mapped[list["TaskInputAsset"]] = relationship(back_populates="task", cascade="all, delete-orphan")
    output_assets: Mapped[list["TaskOutputAsset"]] = relationship(back_populates="task", cascade="all, delete-orphan")
    prompts: Mapped[list["TaskPrompt"]] = relationship(back_populates="task", cascade="all, delete-orphan")


class TaskExecutionPolicy(Base):
    """Singleton submission limits shared by every Studio user."""

    __tablename__ = "task_execution_policies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    max_active_tasks_per_user: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    max_active_tasks_total: Mapped[int] = mapped_column(Integer, nullable=False, default=10)
    updated_by: Mapped[str | None] = mapped_column(String(191), ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, onupdate=now_utc, nullable=False)


class TaskInputAsset(Base):
    __tablename__ = "task_input_assets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[str] = mapped_column(String(64), ForeignKey("workflow_tasks.id", ondelete="CASCADE"), nullable=False)
    asset_id: Mapped[str] = mapped_column(String(64), ForeignKey("assets.id"), nullable=False)
    slot_index: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, nullable=False)

    task: Mapped[WorkflowTask] = relationship(back_populates="input_assets")
    asset: Mapped[Asset] = relationship()


class TaskOutputAsset(Base):
    __tablename__ = "task_output_assets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[str] = mapped_column(String(64), ForeignKey("workflow_tasks.id", ondelete="CASCADE"), nullable=False)
    asset_id: Mapped[str] = mapped_column(String(64), ForeignKey("assets.id"), nullable=False)
    output_role: Mapped[str] = mapped_column(String(32), nullable=False, default="final")
    segment_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, nullable=False)

    task: Mapped[WorkflowTask] = relationship(back_populates="output_assets")
    asset: Mapped[Asset] = relationship()


class TaskPrompt(Base):
    __tablename__ = "task_prompts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[str] = mapped_column(String(64), ForeignKey("workflow_tasks.id", ondelete="CASCADE"), nullable=False, index=True)
    workflow_id: Mapped[str] = mapped_column(String(191), nullable=False, index=True)
    segment_index: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    model_profile_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("model_profiles.id"), nullable=True)
    model_name: Mapped[str | None] = mapped_column(String(191), nullable=True)
    prompt_generation_output_id: Mapped[str | None] = mapped_column(String(64), ForeignKey("prompt_generation_outputs.id"), nullable=True)
    positive_prompt: Mapped[str] = mapped_column(Text, nullable=False, default="")
    negative_prompt: Mapped[str] = mapped_column(Text, nullable=False, default="")
    input_asset_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    output_asset_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    quality_rating: Mapped[int | None] = mapped_column(Integer, nullable=True)
    quality_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    reuse_eligible: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    review_status: Mapped[str] = mapped_column(String(32), nullable=False, default="unreviewed", index=True)
    review_flags_json: Mapped[dict | None] = mapped_column(JSON, nullable=True, default=dict)
    reviewed_by: Mapped[str | None] = mapped_column(String(191), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    reuse_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    metadata_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, onupdate=now_utc, nullable=False)

    task: Mapped[WorkflowTask] = relationship(back_populates="prompts")
    model_profile: Mapped["ModelProfile | None"] = relationship()
    prompt_generation_output: Mapped["PromptGenerationOutput | None"] = relationship()


class ConfigSnapshot(Base):
    __tablename__ = "config_snapshots"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    workflow_id: Mapped[str] = mapped_column(String(191), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(512), nullable=False)
    source: Mapped[str] = mapped_column(String(64), nullable=False, default="studio")
    user_id: Mapped[str | None] = mapped_column(String(191), ForeignKey("users.id"), nullable=True)
    snapshot_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, nullable=False)

    user: Mapped[User | None] = relationship()


class PromptEntry(Base):
    __tablename__ = "prompt_entries"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    workflow_id: Mapped[str | None] = mapped_column(String(191), nullable=True, index=True)
    segment_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    prompt_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(String(64), nullable=False, default="manual")
    created_by: Mapped[str | None] = mapped_column(String(191), ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, nullable=False)

    user: Mapped[User | None] = relationship()


class PromptCategory(Base):
    __tablename__ = "prompt_categories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    group_code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    parent_category_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    scope_type: Mapped[str] = mapped_column(String(32), nullable=False, default="SCENE")
    selection_type: Mapped[str] = mapped_column(String(32), nullable=False, default="MULTIPLE")
    required_yn: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    max_select_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    name_ko: Mapped[str] = mapped_column(String(191), nullable=False)
    name_en: Mapped[str] = mapped_column(String(191), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, onupdate=now_utc, nullable=False)

    # B-06 4단계: 이 관계는 구형 데이터를 위해 남겨두지만(prompt_categories 자체는
    # 이번 단계에서 드롭하지 않음 - TASKS.md가 별도 릴리스로 미루는 것을 명시적으로
    # 허용), 더 이상 어떤 서비스 코드도 여기 의존하지 않는다. prompt_terms.category_id가
    # nullable로 바뀌면서 신규 용어는 이 컬렉션에 절대 속하지 않으므로, delete-orphan은
    # 더 이상 의미 있는 보호 장치가 아니라 오히려 예기치 않은 삭제를 유발할 수 있는
    # 위험 요소라 제거한다.
    terms: Mapped[list["PromptTerm"]] = relationship(back_populates="category")


class PromptScope(Base):
    __tablename__ = "prompt_scopes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    name_ko: Mapped[str] = mapped_column(String(191), nullable=False)
    name_en: Mapped[str] = mapped_column(String(191), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, onupdate=now_utc, nullable=False)

    groups: Mapped[list["PromptCategoryGroup"]] = relationship(back_populates="scope")


class PromptCategoryGroup(Base):
    __tablename__ = "prompt_category_groups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scope_id: Mapped[int] = mapped_column(Integer, ForeignKey("prompt_scopes.id", ondelete="CASCADE"), nullable=False, index=True)
    code: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    name_ko: Mapped[str] = mapped_column(String(191), nullable=False)
    name_en: Mapped[str] = mapped_column(String(191), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, onupdate=now_utc, nullable=False)

    scope: Mapped[PromptScope] = relationship(back_populates="groups")
    subcategories: Mapped[list["PromptSubcategory"]] = relationship(back_populates="category_group")


class PromptSubcategory(Base):
    __tablename__ = "prompt_subcategories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    category_group_id: Mapped[int] = mapped_column(Integer, ForeignKey("prompt_category_groups.id", ondelete="CASCADE"), nullable=False, index=True)
    # B-06 4단계: legacy_category_id 컬럼 제거(마이그레이션 20260810_0013).
    code: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    scope_type: Mapped[str] = mapped_column(String(32), nullable=False, default="SCENE")
    selection_type: Mapped[str] = mapped_column(String(32), nullable=False, default="MULTIPLE")
    required_yn: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    max_select_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    name_ko: Mapped[str] = mapped_column(String(191), nullable=False)
    name_en: Mapped[str] = mapped_column(String(191), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, onupdate=now_utc, nullable=False)

    category_group: Mapped[PromptCategoryGroup] = relationship(back_populates="subcategories")
    keyword_links: Mapped[list["PromptSubcategoryKeyword"]] = relationship(back_populates="subcategory", cascade="all, delete-orphan")


class PromptTerm(Base):
    __tablename__ = "prompt_terms"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # B-06 4단계: category_id를 nullable로 완화(마이그레이션 20260810_0013) - 신형
    # 서브카테고리 귀속은 prompt_subcategory_keywords가 전담하고, 이 FK는 과거 데이터
    # 호환용으로만 남는다. 신규 용어는 category_id=None으로 생성된다.
    category_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("prompt_categories.id", ondelete="CASCADE"), nullable=True)
    code: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    canonical_key: Mapped[str | None] = mapped_column(String(191), nullable=True, index=True)
    label_ko: Mapped[str] = mapped_column(String(191), nullable=False)
    label_en: Mapped[str] = mapped_column(String(191), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    prompt_text: Mapped[str] = mapped_column(Text, nullable=False)
    negative_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    risk_level: Mapped[str] = mapped_column(String(32), nullable=False, default="NONE")
    metadata_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, onupdate=now_utc, nullable=False)

    category: Mapped[PromptCategory | None] = relationship(back_populates="terms")


class PromptCategoryTerm(Base):
    __tablename__ = "prompt_category_terms"

    category_id: Mapped[int] = mapped_column(Integer, ForeignKey("prompt_categories.id", ondelete="CASCADE"), primary_key=True)
    term_id: Mapped[int] = mapped_column(Integer, ForeignKey("prompt_terms.id", ondelete="CASCADE"), primary_key=True)
    default_polarity: Mapped[str] = mapped_column(String(32), nullable=False, default="POSITIVE")
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    active_yn: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    category: Mapped[PromptCategory] = relationship()
    term: Mapped[PromptTerm] = relationship()


class PromptSubcategoryKeyword(Base):
    __tablename__ = "prompt_subcategory_keywords"

    subcategory_id: Mapped[int] = mapped_column(Integer, ForeignKey("prompt_subcategories.id", ondelete="CASCADE"), primary_key=True)
    keyword_id: Mapped[int] = mapped_column(Integer, ForeignKey("prompt_terms.id", ondelete="CASCADE"), primary_key=True)
    default_polarity: Mapped[str] = mapped_column(String(32), nullable=False, default="POSITIVE")
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    active_yn: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    subcategory: Mapped[PromptSubcategory] = relationship(back_populates="keyword_links")
    keyword: Mapped[PromptTerm] = relationship()


class PromptTermRelation(Base):
    __tablename__ = "prompt_term_relations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_term_id: Mapped[int] = mapped_column(Integer, ForeignKey("prompt_terms.id", ondelete="CASCADE"), nullable=False)
    target_term_id: Mapped[int] = mapped_column(Integer, ForeignKey("prompt_terms.id", ondelete="CASCADE"), nullable=False)
    relation_type: Mapped[str] = mapped_column(String(64), nullable=False)
    weight: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    metadata_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, nullable=False)

    source_term: Mapped[PromptTerm] = relationship(foreign_keys=[source_term_id])
    target_term: Mapped[PromptTerm] = relationship(foreign_keys=[target_term_id])


class PromptRule(Base):
    __tablename__ = "prompt_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(191), nullable=False)
    rule_type: Mapped[str] = mapped_column(String(64), nullable=False, default="constraint")
    condition_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    action_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    severity: Mapped[str] = mapped_column(String(32), nullable=False, default="info")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, onupdate=now_utc, nullable=False)


class PromptTemplate(Base):
    __tablename__ = "prompt_templates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(191), nullable=False)
    prompt_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    template_text: Mapped[str] = mapped_column(Text, nullable=False)
    schema_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, onupdate=now_utc, nullable=False)


class PromptSystemPrompt(Base):
    __tablename__ = "prompt_system_prompts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(191), nullable=False)
    provider: Mapped[str] = mapped_column(String(64), nullable=False, default="runpod_vllm")
    model_family: Mapped[str] = mapped_column(String(64), nullable=False, default="qwen")
    prompt_text: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, onupdate=now_utc, nullable=False)


class PromptSystemPromptVersion(Base):
    # B-08: 시스템 지시문 버전 이력. 저장할 때마다 새 상태를 한 행으로 스냅샷해
    # 7a에서 이전 버전으로 되돌릴 수 있게 한다. created_by는 audit_logs와 같은 이유로
    # users.id에 FK를 걸지 않는다(느슨한 참조).
    __tablename__ = "prompt_system_prompt_versions"
    __table_args__ = (
        Index("ix_prompt_system_prompt_versions_code_created", "code", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(191), nullable=False)
    provider: Mapped[str] = mapped_column(String(64), nullable=False, default="runpod_vllm")
    model_family: Mapped[str] = mapped_column(String(64), nullable=False, default="qwen")
    prompt_text: Mapped[str] = mapped_column(Text, nullable=False)
    created_by: Mapped[str | None] = mapped_column(String(191), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, nullable=False)


class ModelProfile(Base):
    __tablename__ = "model_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    model_family: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    model_name: Mapped[str] = mapped_column(String(191), nullable=False)
    model_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    task_type: Mapped[str] = mapped_column(String(64), nullable=False, default="image_to_video")
    prompt_language: Mapped[str] = mapped_column(String(16), nullable=False, default="en")
    supports_negative_prompt: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    supports_prompt_weight: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    capabilities_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    default_parameters_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    active_yn: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, nullable=False)


class PromptTermRendering(Base):
    __tablename__ = "prompt_term_renderings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    term_id: Mapped[int] = mapped_column(Integer, ForeignKey("prompt_terms.id", ondelete="CASCADE"), nullable=False)
    model_profile_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("model_profiles.id", ondelete="CASCADE"), nullable=True)
    language_code: Mapped[str] = mapped_column(String(16), nullable=False, default="en")
    polarity: Mapped[str] = mapped_column(String(32), nullable=False, default="POSITIVE")
    render_text: Mapped[str] = mapped_column(Text, nullable=False)
    render_version: Mapped[str] = mapped_column(String(32), nullable=False, default="v1")
    active_yn: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    term: Mapped[PromptTerm] = relationship()
    model_profile: Mapped[ModelProfile | None] = relationship()


class PromptGenerationRequest(Base):
    __tablename__ = "prompt_generation_requests"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    workflow_id: Mapped[str | None] = mapped_column(String(191), nullable=True, index=True)
    segment_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    language: Mapped[str] = mapped_column(String(16), nullable=False, default="ko")
    scene_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    constraints_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    selected_term_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(64), nullable=False, default="draft", index=True)
    created_by: Mapped[str | None] = mapped_column(String(191), ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, nullable=False)

    user: Mapped[User | None] = relationship()
    outputs: Mapped[list["PromptGenerationOutput"]] = relationship(back_populates="request", cascade="all, delete-orphan")


class PromptGenerationOutput(Base):
    __tablename__ = "prompt_generation_outputs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    request_id: Mapped[str] = mapped_column(String(64), ForeignKey("prompt_generation_requests.id", ondelete="CASCADE"), nullable=False)
    provider: Mapped[str] = mapped_column(String(64), nullable=False, default="builder")
    positive_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    negative_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    used_term_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    added_term_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    warnings_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    raw_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, nullable=False)

    request: Mapped[PromptGenerationRequest] = relationship(back_populates="outputs")


class PromptFeedback(Base):
    __tablename__ = "prompt_feedback"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    output_id: Mapped[str] = mapped_column(String(64), ForeignKey("prompt_generation_outputs.id", ondelete="CASCADE"), nullable=False)
    task_id: Mapped[str | None] = mapped_column(String(64), ForeignKey("workflow_tasks.id"), nullable=True)
    rating: Mapped[int | None] = mapped_column(Integer, nullable=True)
    edited_positive_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    edited_negative_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(191), ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, nullable=False)

    output: Mapped[PromptGenerationOutput] = relationship()
    task: Mapped[WorkflowTask | None] = relationship()
    user: Mapped[User | None] = relationship()


class Report(Base):
    __tablename__ = "reports"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    task_id: Mapped[str | None] = mapped_column(String(64), ForeignKey("workflow_tasks.id"), nullable=True)
    title: Mapped[str] = mapped_column(String(512), nullable=False, default="DOBEDUB STUDIO 작업 리포트")
    storage_backend: Mapped[str] = mapped_column(String(32), nullable=False, default="local")
    storage_key: Mapped[str] = mapped_column(String(1024), nullable=False)
    markdown: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, nullable=False)

    task: Mapped[WorkflowTask | None] = relationship()


Index("ix_task_input_assets_task_slot", TaskInputAsset.task_id, TaskInputAsset.slot_index)
Index("ix_task_output_assets_task_role", TaskOutputAsset.task_id, TaskOutputAsset.output_role, TaskOutputAsset.segment_index)
Index("ix_task_prompts_task_segment", TaskPrompt.task_id, TaskPrompt.segment_index)
Index("ix_task_prompts_workflow_segment", TaskPrompt.workflow_id, TaskPrompt.segment_index)
Index("ix_prompt_terms_category_order", PromptTerm.category_id, PromptTerm.sort_order)
Index("ix_prompt_category_terms_category_order", PromptCategoryTerm.category_id, PromptCategoryTerm.sort_order)
Index("ix_prompt_term_renderings_lookup", PromptTermRendering.term_id, PromptTermRendering.model_profile_id, PromptTermRendering.polarity)
Index("ix_prompt_term_relations_source_type", PromptTermRelation.source_term_id, PromptTermRelation.relation_type)
Index("ix_prompt_generation_requests_workflow_segment", PromptGenerationRequest.workflow_id, PromptGenerationRequest.segment_index)
# 마이그레이션 20260803_0004가 만든 신형 카탈로그 계층 인덱스를 models.py 선언과
# 일치시킨다(드리프트 해소). scope_id·category_group_id 단일 인덱스는 각 컬럼의
# index=True로, 아래 복합 인덱스는 migration과 같은 이름으로 선언.
Index("ix_prompt_subcategory_keywords_subcategory_order", PromptSubcategoryKeyword.subcategory_id, PromptSubcategoryKeyword.sort_order)
