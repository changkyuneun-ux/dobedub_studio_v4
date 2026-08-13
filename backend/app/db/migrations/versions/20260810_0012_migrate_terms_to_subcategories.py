"""migrate terms to subcategories

Revision ID: 20260810_0012
Revises: 20260807_0011
Create Date: 2026-08-10

B-06 step 1 (이관 마이그레이션). Populates the new prompt catalog hierarchy
(prompt_scopes -> prompt_category_groups -> prompt_subcategories ->
prompt_subcategory_keywords) from the legacy hierarchy
(prompt_categories -> prompt_terms).

backend/app/services/prompt_builder_service.sync_prompt_catalog_hierarchy()
already performs this same backfill lazily on every prompt_catalog() call,
but only for *active* categories/terms, and only once something has actually
called that endpoint. This migration makes the same backfill a deterministic
part of the deploy (does not depend on prior app traffic) and additionally
covers what the lazy sync intentionally skips: terms whose legacy category
has no corresponding subcategory (inactive category, a term attached
directly to a POSITIVE_ROOT/NEGATIVE_ROOT category, or an orphaned
category_id). Those go into a per-group "기타" (Other) subcategory instead of
being dropped, per TASKS.md's "용어를 유실시키지 마십시오" requirement.

Every insert is get-or-create against a natural key (prompt_category_groups
.code, prompt_subcategories.code, the (subcategory_id, keyword_id) PK of
prompt_subcategory_keywords), so running this migration against a database
where sync_prompt_catalog_hierarchy() has already run - or running this
migration itself twice - only touches the "기타" fallback rows it is
uniquely responsible for; everything else is a no-op.
"""
from __future__ import annotations

from datetime import datetime
import os

from alembic import op
import sqlalchemy as sa


revision = "20260810_0012"
down_revision = "20260807_0011"
branch_labels = None
depends_on = None


# Mirrors backend/app/services/prompt_builder_service.py's PROMPT_SCOPE_SEED /
# PROMPT_GROUP_LABELS / PROMPT_GROUP_ORDER / FIXED_PROMPT_ROOT_CODES. Copied
# rather than imported, matching this repo's existing migration convention
# (e.g. 20260805_0009_rbac_feature_permissions.py) of keeping migrations
# self-contained and stable even if the service module changes later.
PROMPT_SCOPE_SEED = {
    "POSITIVE": {"nameKo": "Positive", "nameEn": "Positive", "sortOrder": 1},
    "NEGATIVE": {"nameKo": "Negative", "nameEn": "Negative", "sortOrder": 2},
}

PROMPT_GROUP_LABELS = {
    "positive_work_style": ("작품/스타일", "Work / Style"),
    "positive_subject": ("인물/대상", "Subject"),
    "positive_appearance": ("외형/속성", "Appearance"),
    "positive_action_motion": ("동작/움직임", "Action / Motion"),
    "positive_expression_emotion": ("표정/감정", "Expression / Emotion"),
    "positive_scene_background": ("장면/배경", "Scene / Background"),
    "positive_camera_composition": ("카메라/구도", "Camera / Composition"),
    "positive_light_color": ("조명/색감", "Light / Color"),
    "positive_quality_render": ("품질/렌더링", "Quality / Rendering"),
    "negative_quality": ("품질 저하", "Negative Quality"),
    "negative_distortion": ("왜곡/변형", "Distortion"),
    "negative_identity": ("정체성 훼손", "Identity Drift"),
    "negative_motion": ("움직임 오류", "Motion Error"),
    "negative_text_watermark": ("텍스트/워터마크", "Text / Watermark"),
    "negative_camera": ("카메라 오류", "Camera Error"),
    "negative_exclusion": ("금지/제외 요소", "Exclusion"),
    # Fallback groups used only for terms whose legacy category_id resolves
    # to a POSITIVE_ROOT/NEGATIVE_ROOT row directly, or to no row at all
    # (orphaned FK). Not expected to fire on a healthy database.
    "unmapped_legacy_positive": ("미분류(레거시) Positive", "Unmapped (legacy) Positive"),
    "unmapped_legacy_negative": ("미분류(레거시) Negative", "Unmapped (legacy) Negative"),
}
PROMPT_GROUP_ORDER = list(PROMPT_GROUP_LABELS.keys())
FIXED_PROMPT_ROOT_CODES = {"POSITIVE_ROOT", "NEGATIVE_ROOT"}


def _scope_code_for_group(group_code: str) -> str:
    return "NEGATIVE" if "negative" in group_code.lower() else "POSITIVE"


def _group_sort_order(group_code: str) -> int:
    try:
        return (PROMPT_GROUP_ORDER.index(group_code) + 1) * 10
    except ValueError:
        return 1000


def _get_or_create_id(bind, table: str, key_col: str, key_val, insert_values: dict) -> tuple[int, bool]:
    row = bind.execute(sa.text(f"select id from {table} where {key_col} = :key"), {"key": key_val}).fetchone()
    if row:
        return row[0], False
    columns = ", ".join(insert_values.keys())
    placeholders = ", ".join(f":{k}" for k in insert_values.keys())
    bind.execute(sa.text(f"insert into {table} ({columns}) values ({placeholders})"), insert_values)
    row = bind.execute(sa.text(f"select id from {table} where {key_col} = :key"), {"key": key_val}).fetchone()
    return row[0], True


def _get_or_create_group(bind, scope_ids: dict, group_code: str, now: datetime) -> tuple[int, bool]:
    label_ko, label_en = PROMPT_GROUP_LABELS.get(group_code, (group_code, group_code))
    scope_code = _scope_code_for_group(group_code)
    return _get_or_create_id(bind, "prompt_category_groups", "code", group_code, {
        "scope_id": scope_ids[scope_code],
        "code": group_code,
        "name_ko": label_ko,
        "name_en": label_en,
        "sort_order": _group_sort_order(group_code),
        "is_active": 1,
        "created_at": now,
        "updated_at": now,
    })


def _get_or_create_other_subcategory(bind, group_id: int, group_code: str, now: datetime) -> tuple[int, bool]:
    other_code = f"{group_code}_OTHER"
    return _get_or_create_id(bind, "prompt_subcategories", "code", other_code, {
        "category_group_id": group_id,
        "legacy_category_id": None,
        "code": other_code,
        "scope_type": "SCENE",
        "selection_type": "MULTIPLE",
        "required_yn": 0,
        "max_select_count": None,
        "name_ko": "기타",
        "name_en": "Other",
        "description": "이관 시 대응되는 신형 서브카테고리를 찾지 못한 용어를 수용하는 자리 (B-06 0012 마이그레이션)",
        "sort_order": 999,
        "is_active": 1,
        "created_at": now,
        "updated_at": now,
    })


def _link_keyword(bind, subcategory_id: int, term: dict, now: datetime) -> bool:
    default_polarity = "NEGATIVE" if term["negative_text"] and not term["prompt_text"] else "POSITIVE"
    existing = bind.execute(
        sa.text("select 1 from prompt_subcategory_keywords where subcategory_id = :s and keyword_id = :k"),
        {"s": subcategory_id, "k": term["id"]},
    ).fetchone()
    if existing:
        bind.execute(
            sa.text(
                "update prompt_subcategory_keywords set default_polarity = :p, sort_order = :so, "
                "active_yn = :active where subcategory_id = :s and keyword_id = :k"
            ),
            {"p": default_polarity, "so": term["sort_order"], "active": term["is_active"], "s": subcategory_id, "k": term["id"]},
        )
        return False
    bind.execute(
        sa.text(
            "insert into prompt_subcategory_keywords (subcategory_id, keyword_id, default_polarity, sort_order, active_yn) "
            "values (:s, :k, :p, :so, :active)"
        ),
        {"s": subcategory_id, "k": term["id"], "p": default_polarity, "so": term["sort_order"], "active": term["is_active"]},
    )
    return True


def upgrade() -> None:
    if os.environ.get("PRESERVE_EXISTING_CATALOG_DATA", "0") == "1":
        # The legacy v3 RDS already owns this catalog's rows.  During a v4
        # bridge migration, preserve those rows exactly as they are instead of
        # backfilling or updating keyword links.
        print("[0012_migrate_terms_to_subcategories] skipped: preserving existing catalog data")
        return

    bind = op.get_bind()
    now = datetime.utcnow()

    stats = {
        "scopesCreated": 0,
        "groupsCreated": 0,
        "subcategoriesCreated": 0,
        "keywordLinksCreated": 0,
        "keywordLinksAlreadyPresent": 0,
        "termsTotal": 0,
        "termsViaOwnCategory": 0,
        "termsViaOtherFallback": 0,
    }
    other_subcategories_used: set[str] = set()

    # 1) scopes
    scope_ids = {}
    for code, meta in PROMPT_SCOPE_SEED.items():
        scope_id, created = _get_or_create_id(bind, "prompt_scopes", "code", code, {
            "code": code,
            "name_ko": meta["nameKo"],
            "name_en": meta["nameEn"],
            "sort_order": meta["sortOrder"],
            "is_active": 1,
            "created_at": now,
            "updated_at": now,
        })
        scope_ids[code] = scope_id
        if created:
            stats["scopesCreated"] += 1

    # 2) active, non-root legacy categories -> category groups + subcategories.
    # Mirrors sync_prompt_catalog_hierarchy()'s own active-only scope exactly,
    # so this stays idempotent whether or not that lazy sync has already run.
    categories = bind.execute(sa.text(
        "select id, code, group_code, scope_type, selection_type, required_yn, "
        "max_select_count, name_ko, name_en, description, sort_order, is_active "
        "from prompt_categories where is_active = 1"
    )).mappings().all()

    subcategory_id_by_category_id: dict[int, int] = {}
    group_id_by_code: dict[str, int] = {}
    for category in categories:
        if category["code"] in FIXED_PROMPT_ROOT_CODES:
            continue
        group_id = group_id_by_code.get(category["group_code"])
        if group_id is None:
            group_id, group_created = _get_or_create_group(bind, scope_ids, category["group_code"], now)
            group_id_by_code[category["group_code"]] = group_id
            if group_created:
                stats["groupsCreated"] += 1

        subcategory_id, created = _get_or_create_id(bind, "prompt_subcategories", "code", category["code"], {
            "category_group_id": group_id,
            "legacy_category_id": category["id"],
            "code": category["code"],
            "scope_type": category["scope_type"],
            "selection_type": category["selection_type"],
            "required_yn": category["required_yn"],
            "max_select_count": category["max_select_count"],
            "name_ko": category["name_ko"],
            "name_en": category["name_en"],
            "description": category["description"],
            "sort_order": category["sort_order"],
            "is_active": category["is_active"],
            "created_at": now,
            "updated_at": now,
        })
        subcategory_id_by_category_id[category["id"]] = subcategory_id
        if created:
            stats["subcategoriesCreated"] += 1

    # Legacy category rows keyed by id, including inactive ones - needed below
    # to find a group_code for the "기타" fallback even when the category
    # itself was excluded from step 2 for being inactive.
    all_categories_by_id = {
        row["id"]: row
        for row in bind.execute(sa.text(
            "select id, code, group_code, is_active from prompt_categories"
        )).mappings().all()
    }

    # 3) every legacy term (active or not) must end up linked somewhere.
    terms = bind.execute(sa.text(
        "select id, category_id, prompt_text, negative_text, sort_order, is_active from prompt_terms"
    )).mappings().all()

    for term in terms:
        stats["termsTotal"] += 1
        subcategory_id = subcategory_id_by_category_id.get(term["category_id"])
        if subcategory_id is not None:
            created = _link_keyword(bind, subcategory_id, term, now)
            stats["termsViaOwnCategory"] += 1
            stats["keywordLinksCreated" if created else "keywordLinksAlreadyPresent"] += 1
            continue

        # Fallback path: term's category is inactive, is a ROOT category, or
        # does not exist at all.
        category = all_categories_by_id.get(term["category_id"])
        if category is not None and category["code"] not in FIXED_PROMPT_ROOT_CODES:
            group_code = category["group_code"]
        elif category is not None:
            # Term attached directly to POSITIVE_ROOT/NEGATIVE_ROOT.
            group_code = "unmapped_legacy_negative" if category["code"] == "NEGATIVE_ROOT" else "unmapped_legacy_positive"
        else:
            # Fully orphaned category_id; fall back to the term's own content.
            group_code = "unmapped_legacy_negative" if (term["negative_text"] and not term["prompt_text"]) else "unmapped_legacy_positive"

        group_id = group_id_by_code.get(group_code)
        if group_id is None:
            group_id, group_created = _get_or_create_group(bind, scope_ids, group_code, now)
            group_id_by_code[group_code] = group_id
            if group_created:
                stats["groupsCreated"] += 1

        other_subcategory_id, other_created = _get_or_create_other_subcategory(bind, group_id, group_code, now)
        if other_created:
            stats["subcategoriesCreated"] += 1
        created = _link_keyword(bind, other_subcategory_id, term, now)
        stats["termsViaOtherFallback"] += 1
        other_subcategories_used.add(f"{group_code}_OTHER")
        stats["keywordLinksCreated" if created else "keywordLinksAlreadyPresent"] += 1

    print(
        "[0012_migrate_terms_to_subcategories] "
        f"scopesCreated={stats['scopesCreated']} "
        f"groupsCreated={stats['groupsCreated']} "
        f"subcategoriesCreated={stats['subcategoriesCreated']} "
        f"termsTotal={stats['termsTotal']} "
        f"termsViaOwnCategory={stats['termsViaOwnCategory']} "
        f"termsViaOtherFallback={stats['termsViaOtherFallback']} "
        f"otherSubcategoriesUsed={sorted(other_subcategories_used)} "
        f"keywordLinksCreated={stats['keywordLinksCreated']} "
        f"keywordLinksAlreadyPresent={stats['keywordLinksAlreadyPresent']}"
    )


def downgrade() -> None:
    bind = op.get_bind()
    # New-hierarchy tables are not yet read or written by the app outside of
    # sync_prompt_catalog_hierarchy()'s own lazy, idempotent backfill (B-06
    # steps 2/3 have not landed yet), so reverting this migration can safely
    # clear them entirely - the next GET /api/prompts/catalog call will
    # recreate the active-category portion on its own, and legacy tables
    # (prompt_categories/prompt_terms) are untouched either way.
    bind.execute(sa.text("delete from prompt_subcategory_keywords"))
    bind.execute(sa.text("delete from prompt_subcategories"))
    bind.execute(sa.text("delete from prompt_category_groups"))
    bind.execute(sa.text("delete from prompt_scopes"))
