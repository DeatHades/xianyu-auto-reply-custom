"""
统一卡券匹配服务

功能：
1. 提供统一的卡券查询方法（通过关联表查询，含向后兼容回退）
2. 提供统一的规格匹配逻辑（完全匹配 > 通用卡券）
3. 提供批量查询商品卡券配置状态
4. 被 backend-web、websocket、scheduler 三个服务统一调用

匹配优先级：
- 完全匹配：spec_name + spec_value 都匹配的多规格卡券
- 通用卡券：is_multi_spec=False 的卡券，作为兜底
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from loguru import logger
from sqlalchemy import bindparam, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from common.models.card import Card
from common.models.card_item_relation import CardItemRelation
from common.utils.time_utils import safe_isoformat


class CardMatcher:
    """统一卡券匹配器"""

    def __init__(self, session: AsyncSession):
        """
        初始化卡券匹配器

        Args:
            session: 异步数据库会话
        """
        self.session = session

    async def get_cards_by_item_id(
        self,
        item_id: str,
        spec_name: Optional[str] = None,
        spec_value: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        根据商品ID获取匹配的卡券列表（统一入口）

        查询顺序：
        1. 优先从 xy_card_item_relations 关联表查询
        2. 关联表无数据时，回退到 xy_cards.item_id 字段
        3. 对查询结果进行规格匹配过滤

        匹配优先级：
        1. 多规格卡券完全匹配
        2. 普通卡券作为通用兜底

        Args:
            item_id: 商品ID
            spec_name: 规格名称（可选）
            spec_value: 规格值（可选）

        Returns:
            匹配的卡券字典列表
        """

        # 1. 优先从关联表查询
        relation_rows = await self._query_cards_with_source(item_id)

        if relation_rows:
            all_cards = []

            for card, card_source, dock_record_id in relation_rows:
                card_dict = self._card_to_dict(card)
                card_dict["card_source"] = card_source or "own"
                card_dict["dock_record_id"] = dock_record_id
                all_cards.append(card_dict)

            # 规格匹配
            matched = self._match_card_dicts_by_spec(
                all_cards,
                spec_name,
                spec_value,
            )

            # 按 card.id 去重
            matched = self._dedup_cards_by_id(matched)

            logger.info(
                f"卡券匹配: item_id={item_id}, 来源=关联表, "
                f"查询到={len(all_cards)}条, "
                f"规格过滤/去重后={len(matched)}张, "
                f"spec_name={spec_name}, spec_value={spec_value}"
            )

            return matched

        # 2. 关联表无数据，回退到旧字段
        legacy_cards = await self._query_cards_from_legacy(item_id)

        if not legacy_cards:
            logger.info(
                f"卡券匹配: item_id={item_id}, 未找到任何卡券"
            )
            return []

        matched = self._match_cards_by_spec(
            legacy_cards,
            spec_name,
            spec_value,
        )

        for card_dict in matched:
            card_dict["card_source"] = "own"
            card_dict["dock_record_id"] = None

        # 保持一致行为
        matched = self._dedup_cards_by_id(matched)

        logger.info(
            f"卡券匹配: item_id={item_id}, 来源=旧字段, "
            f"查询到={len(legacy_cards)}张, "
            f"规格过滤/去重后={len(matched)}张, "
            f"spec_name={spec_name}, spec_value={spec_value}"
        )

        return matched

    @staticmethod
    def _dedup_cards_by_id(
        cards: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        按 card.id 去重，优先保留 card_source='own' 的记录

        Args:
            cards: 卡券字典列表

        Returns:
            去重后的卡券字典列表
        """

        best_by_id: Dict[Any, Dict[str, Any]] = {}
        order: List[Any] = []

        for card in cards:
            card_id = card.get("id")

            if card_id is None:
                continue

            source = card.get("card_source") or "own"

            if card_id not in best_by_id:
                best_by_id[card_id] = card
                order.append(card_id)

            elif (
                source == "own"
                and best_by_id[card_id].get("card_source") != "own"
            ):
                best_by_id[card_id] = card

        return [
            best_by_id[card_id]
            for card_id in order
        ]

    async def get_all_cards_by_item_id(
        self,
        item_id: str,
    ) -> List[Dict[str, Any]]:
        """
        获取商品关联的所有卡券（管理展示用）

        不过滤启用状态和规格。

        Args:
            item_id: 商品ID

        Returns:
            所有关联的卡券字典列表
        """

        stmt = (
            select(
                Card,
                CardItemRelation.source,
                CardItemRelation.dock_record_id,
            )
            .join(
                CardItemRelation,
                Card.id == CardItemRelation.card_id,
            )
            .where(
                CardItemRelation.item_id == item_id
            )
        )

        result = await self.session.execute(stmt)
        rows = result.all()

        if rows:
            cards_out = []

            for row in rows:
                card_dict = self._card_to_dict(row[0])
                card_dict["card_source"] = row[1] or "own"
                card_dict["dock_record_id"] = row[2]
                cards_out.append(card_dict)

            return cards_out

        # 回退旧字段
        legacy_stmt = (
            select(Card)
            .where(Card.item_id == item_id)
        )

        legacy_result = await self.session.execute(
            legacy_stmt
        )

        cards = list(
            legacy_result.scalars().all()
        )

        result_list = []

        for card in cards:
            card_dict = self._card_to_dict(card)
            card_dict["card_source"] = "own"
            card_dict["dock_record_id"] = None
            result_list.append(card_dict)

        return result_list

    async def get_card_item_ids(
        self,
        card_id: int,
    ) -> List[str]:
        """
        获取卡券关联的所有商品ID列表
        """

        stmt = (
            select(CardItemRelation.item_id)
            .where(
                CardItemRelation.card_id == card_id
            )
        )

        result = await self.session.execute(stmt)

        return [
            row[0]
            for row in result.all()
        ]

    async def get_items_with_card_status(
        self,
        item_ids: List[str],
    ) -> Dict[str, bool]:
        """
        批量查询商品是否配置了卡券

        Args:
            item_ids: 商品ID列表

        Returns:
            {item_id: True/False}
        """

        if not item_ids:
            return {}

        relation_items: set = set()

        try:
            stmt = (
                select(CardItemRelation.item_id)
                .where(
                    CardItemRelation.item_id.in_(item_ids)
                )
                .distinct()
            )

            result = await self.session.execute(stmt)

            relation_items = {
                row[0]
                for row in result.all()
            }

        except Exception as exc:
            logger.warning(
                f"从关联表查询卡券状态失败（回退到旧字段）: {exc}"
            )

        legacy_stmt = (
            select(Card.item_id)
            .where(
                Card.item_id.in_(item_ids),
                Card.enabled == True,
            )
            .distinct()
        )

        legacy_result = await self.session.execute(
            legacy_stmt
        )

        legacy_items = {
            row[0]
            for row in legacy_result.all()
            if row[0]
        }

        configured_items = (
            relation_items | legacy_items
        )

        logger.info(
            f"卡券状态查询: 查询商品数={len(item_ids)}, "
            f"关联表命中={len(relation_items)}, "
            f"旧字段命中={len(legacy_items)}, "
            f"总命中={len(configured_items)}"
        )

        return {
            item_id: item_id in configured_items
            for item_id in item_ids
        }

    async def update_card_item_relations(
        self,
        card_id: int,
        user_id: int,
        item_ids: List[str],
    ) -> Dict[str, int]:
        """
        更新卡券的商品关联关系
        """

        delete_result = await self.session.execute(
            text(
                "DELETE FROM xy_card_item_relations "
                "WHERE card_id = :card_id"
            ),
            {"card_id": card_id},
        )

        removed = delete_result.rowcount

        added = 0

        for item_id in item_ids:
            if not item_id:
                continue

            await self.session.execute(
                text(
                    """
                    INSERT IGNORE INTO xy_card_item_relations
                    (
                        user_id,
                        card_id,
                        item_id,
                        dock_record_id,
                        created_at,
                        updated_at
                    )
                    VALUES
                    (
                        :user_id,
                        :card_id,
                        :item_id,
                        0,
                        NOW(),
                        NOW()
                    )
                    """
                ),
                {
                    "user_id": user_id,
                    "card_id": card_id,
                    "item_id": item_id,
                },
            )

            added += 1

        await self.session.flush()

        return {
            "added": added,
            "removed": removed,
        }

    async def update_item_card_relations(
        self,
        item_id: str,
        user_id: int,
        card_relations: Optional[
            List[Dict[str, Any]]
        ] = None,
    ) -> Dict[str, int]:
        """
        更新商品关联的卡券列表
        """

        delete_result = await self.session.execute(
            text(
                "DELETE FROM xy_card_item_relations "
                "WHERE item_id = :item_id"
            ),
            {"item_id": item_id},
        )

        removed = delete_result.rowcount
        added = 0

        for rel in card_relations or []:
            card_id = rel.get("card_id")

            if not card_id:
                continue

            source = rel.get(
                "source",
                "own",
            )

            dock_record_id = (
                rel.get("dock_record_id") or 0
            )

            await self.session.execute(
                text(
                    """
                    INSERT INTO xy_card_item_relations
                    (
                        user_id,
                        card_id,
                        item_id,
                        source,
                        dock_record_id,
                        created_at,
                        updated_at
                    )
                    VALUES
                    (
                        :user_id,
                        :card_id,
                        :item_id,
                        :source,
                        :dock_record_id,
                        NOW(),
                        NOW()
                    )
                    """
                ),
                {
                    "user_id": user_id,
                    "card_id": card_id,
                    "item_id": item_id,
                    "source": source,
                    "dock_record_id": dock_record_id,
                },
            )

            added += 1

        await self.session.flush()

        return {
            "added": added,
            "removed": removed,
        }

    async def batch_bind_cards_to_items(
        self,
        user_id: int,
        card_ids: List[int],
        item_ids: List[str],
    ) -> Dict[str, int]:
        """
        批量绑定卡券到商品
        """

        success_count = 0
        fail_count = 0

        for card_id in card_ids:
            for item_id in item_ids:
                if not item_id:
                    continue

                try:
                    result = await self.session.execute(
                        text(
                            """
                            INSERT IGNORE INTO xy_card_item_relations
                            (
                                user_id,
                                card_id,
                                item_id,
                                dock_record_id,
                                created_at,
                                updated_at
                            )
                            VALUES
                            (
                                :user_id,
                                :card_id,
                                :item_id,
                                0,
                                NOW(),
                                NOW()
                            )
                            """
                        ),
                        {
                            "user_id": user_id,
                            "card_id": card_id,
                            "item_id": item_id,
                        },
                    )

                    if result.rowcount > 0:
                        success_count += 1

                except Exception as exc:
                    logger.warning(
                        f"绑定卡券 {card_id} "
                        f"到商品 {item_id} 失败: {exc}"
                    )

                    fail_count += 1

        await self.session.flush()

        return {
            "success_count": success_count,
            "fail_count": fail_count,
        }

    async def delete_relations_by_card_id(
        self,
        card_id: int,
    ) -> int:
        """
        删除卡券的所有关联记录
        """

        result = await self.session.execute(
            text(
                "DELETE FROM xy_card_item_relations "
                "WHERE card_id = :card_id"
            ),
            {"card_id": card_id},
        )

        return result.rowcount

    async def delete_relations_by_item_id(
        self,
        item_id: str,
    ) -> int:
        """
        删除商品的所有关联记录
        """

        result = await self.session.execute(
            text(
                "DELETE FROM xy_card_item_relations "
                "WHERE item_id = :item_id"
            ),
            {"item_id": item_id},
        )

        return result.rowcount

    async def delete_relation_by_card_and_item(
        self,
        card_id: int,
        item_id: str,
    ) -> bool:
        """
        删除指定卡券与指定商品的关联记录
        """

        result = await self.session.execute(
            text(
                "DELETE FROM xy_card_item_relations "
                "WHERE card_id = :card_id "
                "AND item_id = :item_id"
            ),
            {
                "card_id": card_id,
                "item_id": item_id,
            },
        )

        removed = result.rowcount

        if removed > 0:
            logger.info(
                f"删除卡券-商品关联: "
                f"card_id={card_id}, "
                f"item_id={item_id}"
            )

        return removed > 0

    async def batch_delete_relations_by_item_ids(
        self,
        item_ids: List[str],
    ) -> int:
        """
        批量清空多个商品的所有卡券关联记录
        """

        if not item_ids:
            return 0

        del_stmt = (
            text(
                """
                DELETE FROM xy_card_item_relations
                WHERE item_id IN :item_ids
                """
            )
            .bindparams(
                bindparam(
                    "item_ids",
                    expanding=True,
                )
            )
        )

        result = await self.session.execute(
            del_stmt,
            {"item_ids": item_ids},
        )

        removed = result.rowcount

        upd_stmt = (
            text(
                """
                UPDATE xy_cards
                SET item_id = NULL
                WHERE item_id IN :item_ids
                """
            )
            .bindparams(
                bindparam(
                    "item_ids",
                    expanding=True,
                )
            )
        )

        await self.session.execute(
            upd_stmt,
            {"item_ids": item_ids},
        )

        await self.session.flush()

        logger.info(
            f"批量清空商品关联卡券: "
            f"商品数={len(item_ids)}, "
            f"删除关联记录={removed}"
        )

        return removed

    # ==================== 内部方法 ====================

    async def _query_cards_with_source(
        self,
        item_id: str,
    ) -> List[tuple]:
        """
        从关联表查询商品关联的启用卡券
        """

        stmt = (
            select(
                Card,
                CardItemRelation.source,
                CardItemRelation.dock_record_id,
            )
            .join(
                CardItemRelation,
                Card.id == CardItemRelation.card_id,
            )
            .where(
                CardItemRelation.item_id == item_id,
                Card.enabled == True,
            )
        )

        result = await self.session.execute(stmt)

        return list(result.all())

    async def _query_cards_from_legacy(
        self,
        item_id: str,
    ) -> List[Card]:
        """
        从 xy_cards.item_id 字段查询
        """

        stmt = (
            select(Card)
            .where(
                Card.item_id == item_id,
                Card.enabled == True,
            )
        )

        result = await self.session.execute(stmt)

        return list(
            result.scalars().all()
        )

    def _match_cards_by_spec(
        self,
        cards: List[Card],
        spec_name: Optional[str],
        spec_value: Optional[str],
    ) -> List[Dict[str, Any]]:
        """
        根据规格信息过滤匹配的卡券

        匹配优先级：

        1. 多规格卡券完全匹配
           spec_name + spec_value 都一致

        2. 通用卡券兜底
           is_multi_spec=False

        即使订单带有规格信息，只要没有匹配到对应的
        多规格卡券，也会返回普通卡券。
        """

        has_spec_info = bool(
            spec_name and spec_value
        )

        exact_matched = []
        generic_cards = []

        for card in cards:

            # 多规格卡券
            if card.is_multi_spec:

                if has_spec_info:

                    card_sn = (
                        card.spec_name or ""
                    ).strip().lower()

                    card_sv = (
                        card.spec_value or ""
                    ).strip().lower()

                    input_sn = (
                        spec_name
                    ).strip().lower()

                    input_sv = (
                        spec_value
                    ).strip().lower()

                    if (
                        card_sn == input_sn
                        and card_sv == input_sv
                    ):
                        exact_matched.append(
                            self._card_to_dict(card)
                        )

                        logger.info(
                            f"多规格卡券匹配成功: "
                            f"{card.name} "
                            f"[{spec_name}:{spec_value}]"
                        )

                    else:
                        logger.debug(
                            f"多规格卡券匹配失败: "
                            f"卡券["
                            f"{card.spec_name}:"
                            f"{card.spec_value}"
                            f"] "
                            f"vs 订单["
                            f"{spec_name}:"
                            f"{spec_value}"
                            f"]"
                        )

            # 普通卡券
            else:
                generic_cards.append(
                    self._card_to_dict(card)
                )

        # 优先返回精确匹配的多规格卡券
        if exact_matched:
            return exact_matched

        # 没有多规格精确匹配时
        # 返回普通通用卡券
        if generic_cards:
            logger.info(
                f"未匹配到对应多规格卡券，"
                f"回退通用卡券: "
                f"spec_name={spec_name}, "
                f"spec_value={spec_value}, "
                f"通用卡券数量={len(generic_cards)}"
            )

        return generic_cards

    def _match_card_dicts_by_spec(
        self,
        card_dicts: List[Dict[str, Any]],
        spec_name: Optional[str],
        spec_value: Optional[str],
    ) -> List[Dict[str, Any]]:
        """
        根据规格信息过滤匹配的卡券（字典版本）

        匹配优先级：

        1. 多规格卡券完全匹配
           spec_name + spec_value 都一致

        2. 通用卡券兜底
           is_multi_spec=False

        这个方法用于关联表查询后的字典数据。

        即使订单带有规格信息，只要没有匹配到对应的
        多规格卡券，也会返回普通卡券。
        """

        has_spec_info = bool(
            spec_name and spec_value
        )

        exact_matched = []
        generic_cards = []

        for cd in card_dicts:

            # 多规格卡券
            if cd.get("is_multi_spec"):

                if has_spec_info:

                    card_sn = (
                        cd.get("spec_name") or ""
                    ).strip().lower()

                    card_sv = (
                        cd.get("spec_value") or ""
                    ).strip().lower()

                    input_sn = (
                        spec_name
                    ).strip().lower()

                    input_sv = (
                        spec_value
                    ).strip().lower()

                    if (
                        card_sn == input_sn
                        and card_sv == input_sv
                    ):
                        exact_matched.append(cd)

                        logger.info(
                            f"多规格卡券匹配成功: "
                            f"{cd.get('name')} "
                            f"[{spec_name}:{spec_value}]"
                        )

                    else:
                        logger.debug(
                            f"多规格卡券匹配失败: "
                            f"卡券["
                            f"{cd.get('spec_name')}:"
                            f"{cd.get('spec_value')}"
                            f"] "
                            f"vs 订单["
                            f"{spec_name}:"
                            f"{spec_value}"
                            f"]"
                        )

            # 普通卡券作为通用兜底
            else:
                generic_cards.append(cd)

        # 优先返回完全匹配的多规格卡券
        if exact_matched:
            return exact_matched

        # 如果没有匹配到多规格卡券
        # 则返回普通通用卡券
        if generic_cards:
            logger.info(
                f"未匹配到对应多规格卡券，"
                f"回退通用卡券: "
                f"spec_name={spec_name}, "
                f"spec_value={spec_value}, "
                f"通用卡券数量={len(generic_cards)}"
            )

        return generic_cards

    @staticmethod
    def _card_to_dict(
        card: Card,
    ) -> Dict[str, Any]:
        """
        将 Card 对象转换为字典
        """

        # 解析 api_config JSON
        api_config = None

        if card.api_config:
            try:
                api_config = json.loads(
                    card.api_config
                )
            except (
                json.JSONDecodeError,
                TypeError,
            ):
                api_config = card.api_config

        # 解析 image_urls JSON
        image_urls = None

        if card.image_urls:
            try:
                image_urls = json.loads(
                    card.image_urls
                )
            except (
                json.JSONDecodeError,
                TypeError,
            ):
                image_urls = None

        return {
            "id": card.id,
            "user_id": card.user_id,
            "item_id": card.item_id,
            "name": card.name,
            "type": card.type,
            "description": card.description,
            "enabled": card.enabled,
            "delay_seconds": (
                card.delay_seconds or 0
            ),
            "use_no_logistics_form": bool(
                card.use_no_logistics_form
            ),
            "delivery_count": card.delivery_count,
            "is_multi_spec": (
                card.is_multi_spec or False
            ),
            "spec_name": card.spec_name,
            "spec_value": card.spec_value,
            "api_config": api_config,
            "text_content": card.text_content,
            "data_content": card.data_content,
            "image_url": card.image_url,
            "image_urls": image_urls,
            "created_at": safe_isoformat(
                card.created_at
            ),
            "updated_at": safe_isoformat(
                card.updated_at
            ),
        }