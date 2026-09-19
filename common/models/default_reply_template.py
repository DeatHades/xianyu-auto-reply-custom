"""默认回复模板模型"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, Boolean, DateTime, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from common.db.base_class import Base


class DefaultReplyTemplate(Base):
    """默认回复模板表（用户级模板库，可绑定多个商品）"""

    __tablename__ = "xy_default_reply_templates"

    __table_args__ = (
        Index("idx_drt_owner_enabled", "owner_id", "enabled"),
        Index("idx_drt_owner_name", "owner_id", "name"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True, comment="模板ID")
    owner_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True, comment="所属用户ID")
    name: Mapped[str] = mapped_column(String(255), nullable=False, comment="模板名称")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1", comment="是否启用")
    reply_type: Mapped[str] = mapped_column(String(32), default="text", server_default="text", comment="回复类型：text-文本，api-接口，external_contact-站外联系方式")
    reply_content: Mapped[Optional[str]] = mapped_column(Text, nullable=True, comment="回复内容")
    reply_image: Mapped[Optional[str]] = mapped_column(String(512), nullable=True, comment="回复图片URL")
    api_url: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True, comment="API地址(reply_type=api时POST此地址)")
    api_timeout: Mapped[int] = mapped_column(Integer, default=80, server_default="80", comment="API请求超时时间(秒)")
    location_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, comment="站外联系方式定位名称")
    location_longitude: Mapped[Optional[str]] = mapped_column(String(32), nullable=True, comment="站外联系方式经度")
    location_latitude: Mapped[Optional[str]] = mapped_column(String(32), nullable=True, comment="站外联系方式纬度")
    location_title: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, comment="站外联系方式位置标题")
    location_subtitle: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, comment="站外联系方式位置副标题")
    reply_once: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0", comment="只回复一次")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), comment="创建时间")
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now(), comment="更新时间")


class DefaultReplyTemplateItemRelation(Base):
    """默认回复模板与商品绑定关系（一个商品最多绑定一个模板）"""

    __tablename__ = "xy_default_reply_template_item_relations"

    __table_args__ = (
        UniqueConstraint("owner_id", "account_id", "item_id", name="uk_drtir_owner_account_item"),
        Index("idx_drtir_template", "template_id"),
        Index("idx_drtir_owner_account_item", "owner_id", "account_id", "item_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True, comment="关系ID")
    owner_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True, comment="所属用户ID")
    template_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True, comment="默认回复模板ID")
    account_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True, comment="闲鱼账号标识")
    item_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True, comment="商品ID")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), comment="创建时间")
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now(), comment="更新时间")
