from __future__ import annotations

from sqlalchemy import func, select

from backend.app.core.timezone_utils import UTC_TIMEZONE, timestamp_fields, utc_now
from backend.app.db.models import Asset, Collection, CollectionItem
from backend.app.db.session import SessionLocal
from backend.app.services.task_tracking_service import _asset_to_json


class CollectionNotEmptyError(ValueError):
    """분류된 자산이 남아 있는 컬렉션은 삭제하지 않는다."""

    def __init__(self, name: str, item_count: int):
        self.name = name
        self.item_count = item_count
        super().__init__(f'컬렉션 "{name}"에 분류된 자산이 {item_count}개 있습니다. 자산 분류를 변경한 후 삭제하세요.')


def _collection_payload(collection: Collection, item_count: int) -> dict:
    return {
        "id": collection.id,
        "name": collection.name,
        "createdBy": collection.created_by,
        **timestamp_fields("createdAt", collection.created_at, naive_timezone=UTC_TIMEZONE, source_timezone="UTC", source="collection"),
        "itemCount": item_count,
    }


def list_collections(created_by: str | None = None) -> list[dict]:
    """A-02: 컬렉션 목록. 각 컬렉션의 담긴 자산 수(itemCount)를 함께 센다.
    created_by가 주어지면 해당 사용자가 만든 컬렉션만 반환한다."""
    session = SessionLocal()
    try:
        statement = select(Collection).order_by(Collection.created_at.desc(), Collection.id.desc())
        if created_by:
            statement = statement.where(Collection.created_by == created_by)
        collections = session.scalars(statement).all()
        if not collections:
            return []
        counts = dict(
            session.execute(
                select(CollectionItem.collection_id, func.count())
                .where(CollectionItem.collection_id.in_([c.id for c in collections]))
                .group_by(CollectionItem.collection_id)
            ).all()
        )
        return [_collection_payload(c, int(counts.get(c.id, 0))) for c in collections]
    finally:
        session.close()


def create_collection(name: str, created_by: str | None = None) -> dict:
    clean_name = (name or "").strip()
    if not clean_name:
        raise ValueError("name is required")
    session = SessionLocal()
    try:
        collection = Collection(name=clean_name, created_by=created_by, created_at=utc_now().replace(tzinfo=None))
        session.add(collection)
        session.commit()
        session.refresh(collection)
        return _collection_payload(collection, 0)
    finally:
        session.close()


def delete_collection(collection_id: int) -> None:
    """비어 있는 컬렉션만 삭제한다.

    컬렉션 삭제가 자산 또는 분류 연결을 연쇄 삭제하는 경로가 되지 않도록, 연결된
    자산이 하나라도 있으면 서버에서 409으로 차단한다.
    """
    session = SessionLocal()
    try:
        collection = session.get(Collection, collection_id)
        if collection is None:
            raise KeyError(f"Collection not found: {collection_id}")
        item_count = int(
            session.scalar(
                select(func.count()).select_from(CollectionItem).where(CollectionItem.collection_id == collection_id)
            )
            or 0
        )
        if item_count:
            raise CollectionNotEmptyError(collection.name, item_count)
        session.delete(collection)
        session.commit()
    finally:
        session.close()


def add_collection_item(collection_id: int, asset_id: str) -> dict:
    """컬렉션에 자산을 담는다. 컬렉션·자산이 없으면 KeyError. 이미 담긴 자산이면
    (collection_id, asset_id 복합 PK) 중복 삽입 없이 조용히 넘어가고 최신 상세를 돌려준다."""
    if not asset_id:
        raise ValueError("assetId is required")
    session = SessionLocal()
    try:
        collection = session.get(Collection, collection_id)
        if collection is None:
            raise KeyError(f"Collection not found: {collection_id}")
        if session.get(Asset, asset_id) is None:
            raise KeyError(f"Asset not found: {asset_id}")
        existing = session.get(CollectionItem, (collection_id, asset_id))
        if existing is None:
            next_order = int(
                session.scalar(
                    select(func.coalesce(func.max(CollectionItem.sort_order), 0)).where(
                        CollectionItem.collection_id == collection_id
                    )
                )
                or 0
            )
            session.add(
                CollectionItem(
                    collection_id=collection_id,
                    asset_id=asset_id,
                    sort_order=next_order + 10,
                    created_at=utc_now().replace(tzinfo=None),
                )
            )
            session.commit()
        return _collection_detail(session, collection)
    finally:
        session.close()


def remove_collection_item(collection_id: int, asset_id: str) -> dict:
    """2026-08-11: Asset 관리 화면 통합 - 자산이 여러 컬렉션에 동시에 속할 수
    있는 다대다 구조를 유지하기로 하면서, 컬렉션 칩에 개별 제거 버튼을 붙이려면
    "빼기" API가 필요해졌다(이전엔 add만 있었음). 컬렉션·자산 자체가 없으면
    KeyError, 애초에 담겨 있지 않았으면 조용히 넘어가고 최신 상세를 돌려준다."""
    session = SessionLocal()
    try:
        collection = session.get(Collection, collection_id)
        if collection is None:
            raise KeyError(f"Collection not found: {collection_id}")
        if session.get(Asset, asset_id) is None:
            raise KeyError(f"Asset not found: {asset_id}")
        existing = session.get(CollectionItem, (collection_id, asset_id))
        if existing is not None:
            session.delete(existing)
            session.commit()
        return _collection_detail(session, collection)
    finally:
        session.close()


def get_collection(collection_id: int) -> dict:
    session = SessionLocal()
    try:
        collection = session.get(Collection, collection_id)
        if collection is None:
            raise KeyError(f"Collection not found: {collection_id}")
        return _collection_detail(session, collection)
    finally:
        session.close()


def _collection_detail(session, collection: Collection) -> dict:
    links = session.scalars(
        select(CollectionItem)
        .where(CollectionItem.collection_id == collection.id)
        .order_by(CollectionItem.sort_order.asc(), CollectionItem.asset_id.asc())
    ).all()
    asset_ids = [link.asset_id for link in links]
    assets_by_id = {
        asset.id: asset
        for asset in (session.scalars(select(Asset).where(Asset.id.in_(asset_ids))).all() if asset_ids else [])
    }
    items = []
    for link in links:
        asset = assets_by_id.get(link.asset_id)
        if not asset:
            continue
        item = _asset_to_json(asset)
        item["sortOrder"] = link.sort_order
        items.append(item)
    payload = _collection_payload(collection, len(items))
    payload["items"] = items
    return payload
