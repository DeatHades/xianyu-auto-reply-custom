"""默认回复模板服务"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from common.models.default_reply_template import (
    DefaultReplyTemplate,
    DefaultReplyTemplateItemRelation,
)
from common.models.xy_account import XYAccount
from common.models.xy_catalog_item import XYCatalogItem
from common.utils.time_utils import safe_isoformat


class DefaultReplyTemplateService:
    """默认回复模板库与商品绑定关系服务"""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def list_templates(
        self,
        owner_id: int,
        page: int = 1,
        page_size: int = 20,
        search: str = "",
    ) -> Dict[str, Any]:
        conditions = [DefaultReplyTemplate.owner_id == owner_id]
        if search:
            conditions.append(DefaultReplyTemplate.name.ilike(f"%{search}%"))

        total = (
            await self.session.execute(
                select(func.count(DefaultReplyTemplate.id)).where(*conditions)
            )
        ).scalar() or 0

        stmt = (
            select(DefaultReplyTemplate)
            .where(*conditions)
            .order_by(DefaultReplyTemplate.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        templates = (await self.session.execute(stmt)).scalars().all()
        counts = await self._count_relations(owner_id, [tpl.id for tpl in templates])

        return {
            "list": [self._template_to_dict(tpl, counts.get(tpl.id, 0)) for tpl in templates],
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": (total + page_size - 1) // page_size if total > 0 else 0,
        }

    async def get_template(self, owner_id: int, template_id: int) -> Optional[Dict[str, Any]]:
        template = await self._get_template_model(owner_id, template_id)
        if not template:
            return None
        counts = await self._count_relations(owner_id, [template_id])
        return self._template_to_dict(template, counts.get(template_id, 0), include_content=True)

    async def create_template(self, owner_id: int, data: Dict[str, Any]) -> int:
        template = DefaultReplyTemplate(owner_id=owner_id, **self._normalize_template_data(data))
        self.session.add(template)
        await self.session.commit()
        await self.session.refresh(template)
        return template.id

    async def update_template(self, owner_id: int, template_id: int, data: Dict[str, Any]) -> bool:
        template = await self._get_template_model(owner_id, template_id)
        if not template:
            return False
        for key, value in self._normalize_template_data(data, partial=True).items():
            setattr(template, key, value)
        await self.session.commit()
        return True

    async def delete_template(self, owner_id: int, template_id: int) -> bool:
        template = await self._get_template_model(owner_id, template_id)
        if not template:
            return False
        await self.session.execute(
            delete(DefaultReplyTemplateItemRelation).where(
                DefaultReplyTemplateItemRelation.owner_id == owner_id,
                DefaultReplyTemplateItemRelation.template_id == template_id,
            )
        )
        await self.session.delete(template)
        await self.session.commit()
        return True

    async def get_template_item_ids(self, owner_id: int, template_id: int) -> List[str]:
        stmt = select(DefaultReplyTemplateItemRelation.item_id).where(
            DefaultReplyTemplateItemRelation.owner_id == owner_id,
            DefaultReplyTemplateItemRelation.template_id == template_id,
        )
        rows = await self.session.execute(stmt)
        return list(rows.scalars().all())

    async def get_template_items(self, owner_id: int, template_id: int) -> List[Dict[str, Any]]:
        stmt = (
            select(
                DefaultReplyTemplateItemRelation.account_id,
                DefaultReplyTemplateItemRelation.item_id,
                XYCatalogItem.title,
                XYCatalogItem.price,
            )
            .outerjoin(
                XYAccount,
                (XYAccount.owner_id == DefaultReplyTemplateItemRelation.owner_id)
                & (XYAccount.account_id == DefaultReplyTemplateItemRelation.account_id),
            )
            .outerjoin(
                XYCatalogItem,
                (XYCatalogItem.owner_id == DefaultReplyTemplateItemRelation.owner_id)
                & (XYCatalogItem.account_pk == XYAccount.id)
                & (XYCatalogItem.item_id == DefaultReplyTemplateItemRelation.item_id),
            )
            .where(
                DefaultReplyTemplateItemRelation.owner_id == owner_id,
                DefaultReplyTemplateItemRelation.template_id == template_id,
            )
            .order_by(DefaultReplyTemplateItemRelation.id.desc())
        )
        rows = await self.session.execute(stmt)
        return [
            {
                "account_id": account_id,
                "item_id": item_id,
                "title": title or item_id,
                "price": price,
            }
            for account_id, item_id, title, price in rows.all()
        ]

    async def update_template_items(
        self,
        owner_id: int,
        template_id: int,
        account_id: str,
        item_ids: List[str],
    ) -> Dict[str, int]:
        template = await self._get_template_model(owner_id, template_id)
        if not template:
            raise ValueError("默认回复模板不存在")
        account = await self._get_account(owner_id, account_id)
        if not account:
            raise ValueError("账号不存在")

        normalized_item_ids = self._normalize_item_ids(item_ids)
        valid_item_ids = await self._filter_valid_item_ids(owner_id, account.id, normalized_item_ids)

        delete_result = await self.session.execute(
            delete(DefaultReplyTemplateItemRelation).where(
                DefaultReplyTemplateItemRelation.owner_id == owner_id,
                DefaultReplyTemplateItemRelation.template_id == template_id,
                DefaultReplyTemplateItemRelation.account_id == account_id,
            )
        )
        removed = delete_result.rowcount or 0

        for item_id in valid_item_ids:
            await self._upsert_relation(owner_id, template_id, account_id, item_id)

        await self.session.commit()
        return {"added": len(valid_item_ids), "removed": removed}

    async def bind_item(
        self,
        owner_id: int,
        account_id: str,
        item_id: str,
        template_id: Optional[int],
    ) -> Dict[str, Any]:
        account = await self._get_account(owner_id, account_id)
        if not account:
            raise ValueError("账号不存在")
        if not await self._item_exists(owner_id, account.id, item_id):
            raise ValueError("商品不存在")

        if template_id is None:
            result = await self.session.execute(
                delete(DefaultReplyTemplateItemRelation).where(
                    DefaultReplyTemplateItemRelation.owner_id == owner_id,
                    DefaultReplyTemplateItemRelation.account_id == account_id,
                    DefaultReplyTemplateItemRelation.item_id == item_id,
                )
            )
            await self.session.commit()
            return {"bound": False, "removed": result.rowcount or 0}

        template = await self._get_template_model(owner_id, template_id)
        if not template:
            raise ValueError("默认回复模板不存在")
        await self._upsert_relation(owner_id, template_id, account_id, item_id)
        await self.session.commit()
        return {"bound": True, "template_id": template_id}

    async def get_item_binding(
        self,
        owner_id: int,
        account_id: str,
        item_id: str,
    ) -> Optional[Dict[str, Any]]:
        stmt = (
            select(DefaultReplyTemplateItemRelation, DefaultReplyTemplate)
            .join(
                DefaultReplyTemplate,
                DefaultReplyTemplate.id == DefaultReplyTemplateItemRelation.template_id,
            )
            .where(
                DefaultReplyTemplateItemRelation.owner_id == owner_id,
                DefaultReplyTemplateItemRelation.account_id == account_id,
                DefaultReplyTemplateItemRelation.item_id == item_id,
            )
        )
        row = (await self.session.execute(stmt)).first()
        if not row:
            return None
        relation, template = row
        return {
            "account_id": relation.account_id,
            "item_id": relation.item_id,
            "template": self._template_to_dict(template, include_content=True),
        }

    async def get_bindings_for_items(
        self,
        owner_id: int,
        account_ids: Iterable[str],
        item_ids: Iterable[str],
    ) -> Dict[tuple[str, str], Dict[str, Any]]:
        account_ids_list = list({a for a in account_ids if a})
        item_ids_list = list({i for i in item_ids if i})
        if not account_ids_list or not item_ids_list:
            return {}
        stmt = (
            select(DefaultReplyTemplateItemRelation, DefaultReplyTemplate)
            .join(DefaultReplyTemplate, DefaultReplyTemplate.id == DefaultReplyTemplateItemRelation.template_id)
            .where(
                DefaultReplyTemplateItemRelation.owner_id == owner_id,
                DefaultReplyTemplateItemRelation.account_id.in_(account_ids_list),
                DefaultReplyTemplateItemRelation.item_id.in_(item_ids_list),
            )
        )
        rows = await self.session.execute(stmt)
        result: Dict[tuple[str, str], Dict[str, Any]] = {}
        for relation, template in rows.all():
            result[(relation.account_id, relation.item_id)] = {
                "template_id": relation.template_id,
                "template_name": template.name,
                "enabled": bool(template.enabled),
            }
        return result

    async def get_active_template_for_item(
        self,
        owner_id: int,
        account_id: str,
        item_id: str,
    ) -> Optional[Dict[str, Any]]:
        stmt = (
            select(DefaultReplyTemplate)
            .join(
                DefaultReplyTemplateItemRelation,
                DefaultReplyTemplateItemRelation.template_id == DefaultReplyTemplate.id,
            )
            .where(
                DefaultReplyTemplateItemRelation.owner_id == owner_id,
                DefaultReplyTemplateItemRelation.account_id == account_id,
                DefaultReplyTemplateItemRelation.item_id == item_id,
                DefaultReplyTemplate.enabled.is_(True),
            )
        )
        template = (await self.session.execute(stmt)).scalars().first()
        if not template:
            return None
        return self._template_to_settings(template, item_id)

    async def migrate_item_relation(
        self,
        owner_id: int,
        account_id: str,
        old_item_id: str,
        new_item_id: str,
    ) -> None:
        row = (
            await self.session.execute(
                select(DefaultReplyTemplateItemRelation).where(
                    DefaultReplyTemplateItemRelation.owner_id == owner_id,
                    DefaultReplyTemplateItemRelation.account_id == account_id,
                    DefaultReplyTemplateItemRelation.item_id == old_item_id,
                )
            )
        ).scalars().first()
        if not row:
            return
        exists = (
            await self.session.execute(
                select(DefaultReplyTemplateItemRelation.id).where(
                    DefaultReplyTemplateItemRelation.owner_id == owner_id,
                    DefaultReplyTemplateItemRelation.account_id == account_id,
                    DefaultReplyTemplateItemRelation.item_id == new_item_id,
                )
            )
        ).scalar_one_or_none()
        if not exists:
            self.session.add(
                DefaultReplyTemplateItemRelation(
                    owner_id=owner_id,
                    template_id=row.template_id,
                    account_id=account_id,
                    item_id=new_item_id,
                )
            )
        await self.session.flush()

    async def _get_template_model(self, owner_id: int, template_id: int) -> Optional[DefaultReplyTemplate]:
        return (
            await self.session.execute(
                select(DefaultReplyTemplate).where(
                    DefaultReplyTemplate.owner_id == owner_id,
                    DefaultReplyTemplate.id == template_id,
                )
            )
        ).scalars().first()

    async def _count_relations(self, owner_id: int, template_ids: List[int]) -> Dict[int, int]:
        if not template_ids:
            return {}
        rows = await self.session.execute(
            select(
                DefaultReplyTemplateItemRelation.template_id,
                func.count(DefaultReplyTemplateItemRelation.id),
            )
            .where(
                DefaultReplyTemplateItemRelation.owner_id == owner_id,
                DefaultReplyTemplateItemRelation.template_id.in_(template_ids),
            )
            .group_by(DefaultReplyTemplateItemRelation.template_id)
        )
        return {int(template_id): int(count or 0) for template_id, count in rows.all()}

    async def _get_account(self, owner_id: int, account_id: str) -> Optional[XYAccount]:
        return (
            await self.session.execute(
                select(XYAccount).where(
                    XYAccount.owner_id == owner_id,
                    XYAccount.account_id == account_id,
                )
            )
        ).scalars().first()

    async def _item_exists(self, owner_id: int, account_pk: int, item_id: str) -> bool:
        exists = (
            await self.session.execute(
                select(XYCatalogItem.id).where(
                    XYCatalogItem.owner_id == owner_id,
                    XYCatalogItem.account_pk == account_pk,
                    XYCatalogItem.item_id == item_id,
                )
            )
        ).scalar_one_or_none()
        return exists is not None

    async def _filter_valid_item_ids(
        self,
        owner_id: int,
        account_pk: int,
        item_ids: List[str],
    ) -> List[str]:
        if not item_ids:
            return []
        rows = await self.session.execute(
            select(XYCatalogItem.item_id).where(
                XYCatalogItem.owner_id == owner_id,
                XYCatalogItem.account_pk == account_pk,
                XYCatalogItem.item_id.in_(item_ids),
            )
        )
        valid = set(rows.scalars().all())
        return [item_id for item_id in item_ids if item_id in valid]

    async def _upsert_relation(
        self,
        owner_id: int,
        template_id: int,
        account_id: str,
        item_id: str,
    ) -> None:
        existing = (
            await self.session.execute(
                select(DefaultReplyTemplateItemRelation).where(
                    DefaultReplyTemplateItemRelation.owner_id == owner_id,
                    DefaultReplyTemplateItemRelation.account_id == account_id,
                    DefaultReplyTemplateItemRelation.item_id == item_id,
                )
            )
        ).scalars().first()
        if existing:
            existing.template_id = template_id
            return
        self.session.add(
            DefaultReplyTemplateItemRelation(
                owner_id=owner_id,
                template_id=template_id,
                account_id=account_id,
                item_id=item_id,
            )
        )

    @staticmethod
    def _normalize_item_ids(item_ids: List[str]) -> List[str]:
        seen: set[str] = set()
        result: List[str] = []
        for raw in item_ids or []:
            item_id = str(raw or "").strip()
            if not item_id or item_id in seen:
                continue
            seen.add(item_id)
            result.append(item_id)
        return result

    @staticmethod
    def _normalize_template_data(data: Dict[str, Any], partial: bool = False) -> Dict[str, Any]:
        allowed = {
            "name",
            "enabled",
            "reply_type",
            "reply_content",
            "reply_image",
            "api_url",
            "api_timeout",
            "location_name",
            "location_longitude",
            "location_latitude",
            "location_title",
            "location_subtitle",
            "reply_once",
        }
        normalized: Dict[str, Any] = {}
        for key in allowed:
            if key in data:
                normalized[key] = data[key]
        if not partial:
            normalized.setdefault("enabled", True)
            normalized.setdefault("reply_type", "text")
            normalized.setdefault("reply_content", "")
            normalized.setdefault("reply_image", "")
            normalized.setdefault("api_url", "")
            normalized.setdefault("api_timeout", 80)
            normalized.setdefault("location_name", "")
            normalized.setdefault("location_longitude", "")
            normalized.setdefault("location_latitude", "")
            normalized.setdefault("location_title", "")
            normalized.setdefault("location_subtitle", "")
            normalized.setdefault("reply_once", False)
        if "name" in normalized:
            normalized["name"] = str(normalized["name"] or "").strip()
        if "reply_type" in normalized:
            normalized["reply_type"] = str(normalized["reply_type"] or "text").strip() or "text"
        if "api_timeout" in normalized:
            try:
                normalized["api_timeout"] = int(normalized["api_timeout"] or 80)
            except (TypeError, ValueError):
                normalized["api_timeout"] = 80
        return normalized

    @staticmethod
    def _template_to_dict(
        template: DefaultReplyTemplate,
        bound_count: int = 0,
        include_content: bool = True,
    ) -> Dict[str, Any]:
        data: Dict[str, Any] = {
            "id": template.id,
            "owner_id": template.owner_id,
            "name": template.name,
            "enabled": bool(template.enabled),
            "reply_type": template.reply_type or "text",
            "reply_once": bool(template.reply_once),
            "bound_count": bound_count,
            "created_at": safe_isoformat(template.created_at),
            "updated_at": safe_isoformat(template.updated_at),
        }
        if include_content:
            data.update(
                {
                    "reply_content": template.reply_content or "",
                    "reply_image": template.reply_image or "",
                    "api_url": template.api_url or "",
                    "api_timeout": template.api_timeout or 80,
                    "location_name": template.location_name or "",
                    "location_longitude": template.location_longitude or "",
                    "location_latitude": template.location_latitude or "",
                    "location_title": template.location_title or "",
                    "location_subtitle": template.location_subtitle or "",
                }
            )
        return data

    @staticmethod
    def _template_to_settings(template: DefaultReplyTemplate, item_id: str) -> Dict[str, Any]:
        return {
            "enabled": bool(template.enabled),
            "reply_type": template.reply_type or "text",
            "reply_content": template.reply_content or "",
            "reply_image": template.reply_image or "",
            "api_url": template.api_url or "",
            "api_timeout": template.api_timeout or 80,
            "location_name": template.location_name or "",
            "location_longitude": template.location_longitude or "",
            "location_latitude": template.location_latitude or "",
            "location_title": template.location_title or "",
            "location_subtitle": template.location_subtitle or "",
            "reply_once": bool(template.reply_once),
            "item_id": item_id,
            "template_id": template.id,
            "template_name": template.name,
            "source": "template",
        }
