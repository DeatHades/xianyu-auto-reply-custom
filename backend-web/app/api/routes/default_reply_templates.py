"""默认回复模板管理路由"""
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, File, Query, UploadFile
from pydantic import BaseModel

from app.api import deps
from app.core.paths import STATIC_ROOT
from app.services.default_reply_template_service import DefaultReplyTemplateService
from common.models.user import User
from common.schemas.common import ApiResponse
from common.utils.default_reply_api import normalize_api_timeout, validate_api_url
from common.utils.default_reply_location import EXTERNAL_CONTACT_REPLY_TYPE, validate_external_contact_fields
from common.utils.local_image_upload import ImageUploadError, save_uploaded_image


router = APIRouter(tags=["默认回复模板"])

TEMPLATE_REPLY_UPLOAD_DIR = STATIC_ROOT / "uploads" / "default_reply_template"
TEMPLATE_REPLY_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


class DefaultReplyTemplatePayload(BaseModel):
    name: str
    enabled: bool = True
    reply_type: str = "text"
    reply_content: str = ""
    reply_image: str = ""
    api_url: str = ""
    api_timeout: int = 80
    location_name: str = ""
    location_longitude: str = ""
    location_latitude: str = ""
    location_title: str = ""
    location_subtitle: str = ""
    reply_once: bool = False


class UpdateTemplateItemsPayload(BaseModel):
    account_id: str
    item_ids: List[str]


class BindItemTemplatePayload(BaseModel):
    template_id: Optional[int] = None


async def get_template_service(session=Depends(deps.get_db_session)) -> DefaultReplyTemplateService:
    return DefaultReplyTemplateService(session)


def _validate_template_payload(payload: DefaultReplyTemplatePayload) -> Optional[str]:
    if not payload.name.strip():
        return "请输入模板名称"
    payload.api_timeout = normalize_api_timeout(payload.api_timeout)
    if payload.reply_type == "api":
        valid, err = validate_api_url(payload.api_url)
        if not valid:
            return err
    if payload.reply_type == EXTERNAL_CONTACT_REPLY_TYPE:
        # 这里仅校验字段形态；远程URL/秘钥由实际发送链路复用现有全局配置。
        err = validate_external_contact_fields(
            remote_url="http://127.0.0.1",
            location_name=payload.location_name,
            longitude=payload.location_longitude,
            latitude=payload.location_latitude,
            title=payload.location_title,
            subtitle=payload.location_subtitle,
        )
        if err:
            return err
    return None


@router.get("")
async def list_templates(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    search: str = Query(default=""),
    current_user: User = Depends(deps.get_current_active_user),
    service: DefaultReplyTemplateService = Depends(get_template_service),
):
    return await service.list_templates(
        owner_id=current_user.id,
        page=page,
        page_size=page_size,
        search=search,
    )


@router.post("/upload-image")
async def upload_template_image(
    image: UploadFile = File(...),
    current_user: User = Depends(deps.get_current_active_user),
):
    try:
        _, filename, _ = await save_uploaded_image(
            image,
            TEMPLATE_REPLY_UPLOAD_DIR,
            filename_prefix=str(current_user.id),
        )
    except ImageUploadError as exc:
        return ApiResponse(success=False, message=exc.message)
    return {"success": True, "image_url": f"/static/uploads/default_reply_template/{filename}"}


@router.get("/{template_id}")
async def get_template(
    template_id: int,
    current_user: User = Depends(deps.get_current_active_user),
    service: DefaultReplyTemplateService = Depends(get_template_service),
):
    template = await service.get_template(current_user.id, template_id)
    if not template:
        return ApiResponse(success=False, message="默认回复模板不存在")
    return template


@router.post("")
async def create_template(
    payload: DefaultReplyTemplatePayload,
    current_user: User = Depends(deps.get_current_active_user),
    service: DefaultReplyTemplateService = Depends(get_template_service),
):
    err = _validate_template_payload(payload)
    if err:
        return ApiResponse(success=False, message=err)
    template_id = await service.create_template(current_user.id, payload.model_dump())
    return ApiResponse(success=True, message="默认回复模板已创建", data={"id": template_id})


@router.put("/{template_id}")
async def update_template(
    template_id: int,
    payload: DefaultReplyTemplatePayload,
    current_user: User = Depends(deps.get_current_active_user),
    service: DefaultReplyTemplateService = Depends(get_template_service),
):
    err = _validate_template_payload(payload)
    if err:
        return ApiResponse(success=False, message=err)
    success = await service.update_template(current_user.id, template_id, payload.model_dump())
    if not success:
        return ApiResponse(success=False, message="默认回复模板不存在")
    return ApiResponse(success=True, message="默认回复模板已更新")


@router.delete("/{template_id}")
async def delete_template(
    template_id: int,
    current_user: User = Depends(deps.get_current_active_user),
    service: DefaultReplyTemplateService = Depends(get_template_service),
):
    success = await service.delete_template(current_user.id, template_id)
    if not success:
        return ApiResponse(success=False, message="默认回复模板不存在")
    return ApiResponse(success=True, message="默认回复模板已删除")


@router.get("/{template_id}/item-ids")
async def get_template_item_ids(
    template_id: int,
    current_user: User = Depends(deps.get_current_active_user),
    service: DefaultReplyTemplateService = Depends(get_template_service),
):
    item_ids = await service.get_template_item_ids(current_user.id, template_id)
    return ApiResponse(success=True, data={"item_ids": item_ids})


@router.get("/{template_id}/items")
async def get_template_items(
    template_id: int,
    current_user: User = Depends(deps.get_current_active_user),
    service: DefaultReplyTemplateService = Depends(get_template_service),
):
    items = await service.get_template_items(current_user.id, template_id)
    return {"list": items, "total": len(items)}


@router.put("/{template_id}/items")
async def update_template_items(
    template_id: int,
    payload: UpdateTemplateItemsPayload,
    current_user: User = Depends(deps.get_current_active_user),
    service: DefaultReplyTemplateService = Depends(get_template_service),
):
    try:
        result = await service.update_template_items(
            owner_id=current_user.id,
            template_id=template_id,
            account_id=payload.account_id,
            item_ids=payload.item_ids,
        )
    except ValueError as exc:
        return ApiResponse(success=False, message=str(exc))
    return ApiResponse(success=True, message=f"模板绑定已更新（新增 {result['added']} 个，删除 {result['removed']} 个）", data=result)


@router.get("/item/{account_id}/{item_id}")
async def get_item_template_binding(
    account_id: str,
    item_id: str,
    current_user: User = Depends(deps.get_current_active_user),
    service: DefaultReplyTemplateService = Depends(get_template_service),
):
    binding = await service.get_item_binding(current_user.id, account_id, item_id)
    return ApiResponse(success=True, data=binding or {"account_id": account_id, "item_id": item_id, "template": None})


@router.put("/item/{account_id}/{item_id}")
async def bind_item_template(
    account_id: str,
    item_id: str,
    payload: BindItemTemplatePayload,
    current_user: User = Depends(deps.get_current_active_user),
    service: DefaultReplyTemplateService = Depends(get_template_service),
):
    try:
        result = await service.bind_item(
            owner_id=current_user.id,
            account_id=account_id,
            item_id=item_id,
            template_id=payload.template_id,
        )
    except ValueError as exc:
        return ApiResponse(success=False, message=str(exc))
    return ApiResponse(success=True, message="默认回复模板绑定已更新", data=result)
