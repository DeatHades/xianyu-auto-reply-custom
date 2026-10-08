"""
认证API路由

功能：
1. 用户登录（用户名/邮箱+密码）
2. 令牌验证
3. 用户注册
4. 用户登出
"""
import json
import os
from datetime import timedelta
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import deps
from app.api.routes.captcha import check_email_code
from app.core.security import decode_token, get_password_hash
from common.models.user import User, UserRole, UserStatus
from common.models.passkey import PasskeyChallenge, PasskeyCredential
from common.utils.time_utils import get_beijing_now_naive
from common.schemas.auth import LoginRequest, LoginResponse, VerifyResponse
from common.schemas.common import ApiResponse
from common.schemas.user import UserCreate, UserPublic
from app.services.auth import AuthService
from app.services.user_service import UserService

router = APIRouter(tags=["auth"])


class ResetPasswordRequest(BaseModel):
    """重置密码请求"""
    email: str
    verification_code: str
    new_password: str


class PasskeyVerifyRequest(BaseModel):
    challenge_id: str
    credential: dict
    device_name: str | None = None


def _passkey_config(request: Request) -> tuple[str, str]:
    """获取 RP 配置；生产环境建议显式设置 PASSKEY_RP_ID/ORIGIN。"""
    host = request.url.hostname or ""
    origin = f"{request.url.scheme}://{request.url.netloc}"
    rp_id = os.getenv("PASSKEY_RP_ID", host).strip()
    configured_origin = os.getenv("PASSKEY_ORIGIN", origin).strip()
    if not rp_id or not configured_origin:
        raise HTTPException(status_code=503, detail="Passkey未配置域名")
    if configured_origin.startswith("http://") and host not in {"localhost", "127.0.0.1", "[::1]"}:
        raise HTTPException(status_code=400, detail="Passkey登录必须使用HTTPS域名")
    return rp_id, configured_origin


def _webauthn_imports():
    try:
        from webauthn import (
            generate_authentication_options,
            generate_registration_options,
            verify_authentication_response,
            verify_registration_response,
        )
        from webauthn.helpers import base64url_to_bytes, bytes_to_base64url, options_to_json
        from webauthn.helpers.structs import (
            AuthenticatorSelectionCriteria,
            PublicKeyCredentialDescriptor,
            ResidentKeyRequirement,
            UserVerificationRequirement,
        )
        return locals()
    except ImportError as exc:
        raise HTTPException(status_code=503, detail="Passkey组件未安装，请重新构建后台") from exc


@router.post("/passkey/register/options")
async def passkey_register_options(
    request: Request,
    current_user: User = Depends(deps.get_current_active_user),
    session: AsyncSession = Depends(deps.get_db_session),
) -> dict:
    """为已登录用户生成一次性 Passkey 注册挑战。"""
    rp_id, _ = _passkey_config(request)
    lib = _webauthn_imports()
    existing = (await session.execute(select(PasskeyCredential).where(PasskeyCredential.user_id == current_user.id))).scalars().all()
    options = lib["generate_registration_options"](
        rp_id=rp_id,
        rp_name="闲鱼管理系统",
        user_id=str(current_user.id).encode("utf-8"),
        user_name=current_user.username,
        user_display_name=current_user.username,
        exclude_credentials=[
            lib["PublicKeyCredentialDescriptor"](id=lib["base64url_to_bytes"](item.credential_id))
            for item in existing
        ],
        authenticator_selection=lib["AuthenticatorSelectionCriteria"](
            resident_key=lib["ResidentKeyRequirement"].REQUIRED,
            user_verification=lib["UserVerificationRequirement"].REQUIRED,
        ),
    )
    challenge_id = uuid4().hex
    session.add(PasskeyChallenge(
        id=challenge_id,
        user_id=current_user.id,
        challenge=lib["bytes_to_base64url"](options.challenge),
        purpose="register",
        expires_at=get_beijing_now_naive() + timedelta(minutes=5),
    ))
    await session.commit()
    return {"success": True, "challenge_id": challenge_id, "options": json.loads(lib["options_to_json"](options))}


@router.post("/passkey/register/verify")
async def passkey_register_verify(
    payload: PasskeyVerifyRequest,
    request: Request,
    current_user: User = Depends(deps.get_current_active_user),
    session: AsyncSession = Depends(deps.get_db_session),
) -> dict:
    rp_id, origin = _passkey_config(request)
    lib = _webauthn_imports()
    challenge = (await session.execute(select(PasskeyChallenge).where(
        PasskeyChallenge.id == payload.challenge_id,
        PasskeyChallenge.user_id == current_user.id,
        PasskeyChallenge.purpose == "register",
    ))).scalar_one_or_none()
    if not challenge or challenge.expires_at < get_beijing_now_naive():
        raise HTTPException(status_code=400, detail="Passkey注册挑战已过期，请重试")
    try:
        verified = lib["verify_registration_response"](
            credential=payload.credential,
            expected_challenge=lib["base64url_to_bytes"](challenge.challenge),
            expected_rp_id=rp_id,
            expected_origin=origin,
            require_user_verification=True,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Passkey注册验证失败: {exc}") from exc
    credential_id = lib["bytes_to_base64url"](verified.credential_id)
    existing = (await session.execute(select(PasskeyCredential).where(PasskeyCredential.credential_id == credential_id))).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=409, detail="该通行密钥已经注册")
    session.add(PasskeyCredential(
        user_id=current_user.id,
        credential_id=credential_id,
        public_key=lib["bytes_to_base64url"](verified.credential_public_key),
        sign_count=verified.sign_count,
        device_name=(payload.device_name or "Apple通行密钥")[:120],
    ))
    await session.delete(challenge)
    await session.commit()
    return {"success": True, "message": "通行密钥注册成功"}


@router.post("/passkey/login/options")
async def passkey_login_options(request: Request, session: AsyncSession = Depends(deps.get_db_session)) -> dict:
    """生成 Passkey 登录挑战；不返回用户列表，避免账号枚举。"""
    rp_id, _ = _passkey_config(request)
    lib = _webauthn_imports()
    options = lib["generate_authentication_options"](
        rp_id=rp_id,
        user_verification=lib["UserVerificationRequirement"].REQUIRED,
    )
    challenge_id = uuid4().hex
    session.add(PasskeyChallenge(
        id=challenge_id,
        challenge=lib["bytes_to_base64url"](options.challenge),
        purpose="login",
        expires_at=get_beijing_now_naive() + timedelta(minutes=5),
    ))
    await session.commit()
    return {"success": True, "challenge_id": challenge_id, "options": json.loads(lib["options_to_json"](options))}


@router.post("/passkey/login/verify", response_model=LoginResponse)
async def passkey_login_verify(
    payload: PasskeyVerifyRequest,
    request: Request,
    session: AsyncSession = Depends(deps.get_db_session),
    auth_service: AuthService = Depends(deps.get_auth_service),
) -> LoginResponse:
    rp_id, origin = _passkey_config(request)
    lib = _webauthn_imports()
    challenge = (await session.execute(select(PasskeyChallenge).where(
        PasskeyChallenge.id == payload.challenge_id,
        PasskeyChallenge.purpose == "login",
    ))).scalar_one_or_none()
    if not challenge or challenge.expires_at < get_beijing_now_naive():
        return LoginResponse(success=False, message="Passkey登录挑战已过期，请重试")
    credential_id = payload.credential.get("id")
    record = (await session.execute(select(PasskeyCredential).where(PasskeyCredential.credential_id == credential_id))).scalar_one_or_none()
    if not record:
        return LoginResponse(success=False, message="未找到该通行密钥，请先用密码登录并注册")
    try:
        verified = lib["verify_authentication_response"](
            credential=payload.credential,
            expected_challenge=lib["base64url_to_bytes"](challenge.challenge),
            expected_rp_id=rp_id,
            expected_origin=origin,
            credential_public_key=lib["base64url_to_bytes"](record.public_key),
            credential_current_sign_count=record.sign_count,
            require_user_verification=True,
        )
    except Exception as exc:
        return LoginResponse(success=False, message=f"Passkey验证失败: {exc}")
    user = await session.get(User, record.user_id)
    if not user or user.status != UserStatus.ACTIVE:
        return LoginResponse(success=False, message="账号不存在或已被禁用")
    record.sign_count = verified.new_sign_count
    record.last_used_at = get_beijing_now_naive()
    await session.delete(challenge)
    await session.commit()
    await auth_service.mark_login(user)
    return LoginResponse(
        success=True, message="登录成功", token=auth_service.create_access_token(user),
        refresh_token=auth_service.create_refresh_token(user), user_id=user.id,
        username=user.username, is_admin=user.role == UserRole.ADMIN, account_limit=user.account_limit,
    )


@router.post("/login", response_model=LoginResponse)
async def login_user(
    payload: LoginRequest,
    auth_service: AuthService = Depends(deps.get_auth_service),
    session: AsyncSession = Depends(deps.get_db_session),
) -> LoginResponse:
    user: User | None = None
    error_message: str | None = None

    # 检查是否启用了登录滑动验证码
    from app.services.system_setting_service import SystemSettingService
    setting_service = SystemSettingService(session)
    all_settings = await setting_service.list_settings()
    captcha_enabled_str = all_settings.get("login_captcha_enabled")
    captcha_enabled = captcha_enabled_str in (None, "true", "1")  # 默认开启

    # 账号密码登录和邮箱密码登录需要验证滑动验证码
    if payload.username and payload.password:
        # 账号密码登录 - 需要滑动验证（如果开启）
        if captcha_enabled:
            from app.api.routes.geetest import check_geetest_verified
            
            if not payload.geetest_challenge:
                return LoginResponse(success=False, message="请完成滑动验证")
            
            geetest_ok, geetest_msg = check_geetest_verified(payload.geetest_challenge)
            if not geetest_ok:
                return LoginResponse(success=False, message=geetest_msg)
        
        user, error_message = await auth_service.authenticate_by_username(payload.username, payload.password)
    elif payload.email and payload.password:
        # 邮箱密码登录 - 需要滑动验证（如果开启）
        if captcha_enabled:
            from app.api.routes.geetest import check_geetest_verified
            
            if not payload.geetest_challenge:
                return LoginResponse(success=False, message="请完成滑动验证")
            
            geetest_ok, geetest_msg = check_geetest_verified(payload.geetest_challenge)
            if not geetest_ok:
                return LoginResponse(success=False, message=geetest_msg)
        
        user, error_message = await auth_service.authenticate_by_email(payload.email, payload.password)
    elif payload.email and payload.verification_code:
        # 邮箱验证码登录
        # 验证验证码
        code_valid, code_msg = check_email_code(payload.email, payload.verification_code, "login")
        if not code_valid:
            return LoginResponse(success=False, message=code_msg)
        
        # 根据邮箱查找用户
        user_service = UserService(session)
        user = await user_service.get_by_email(payload.email)
        if not user:
            return LoginResponse(success=False, message="该邮箱未注册")
    else:
        return LoginResponse(success=False, message="请提供有效的登录信息")

    if not user:
        return LoginResponse(success=False, message=error_message or "登录失败")

    if user.status != UserStatus.ACTIVE:
        return LoginResponse(success=False, message="账号已禁用，请联系管理员")

    await auth_service.mark_login(user)
    return LoginResponse(
        success=True,
        message="登录成功",
        token=auth_service.create_access_token(user),
        refresh_token=auth_service.create_refresh_token(user),
        user_id=user.id,
        username=user.username,
        is_admin=user.role == UserRole.ADMIN,
        account_limit=user.account_limit,
    )


@router.get("/verify", response_model=VerifyResponse)
async def verify_token(
    request: Request,
    session: AsyncSession = Depends(deps.get_db_session),
) -> VerifyResponse:
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        return VerifyResponse(authenticated=False)

    token = auth_header.split(" ", 1)[1]
    try:
        payload = decode_token(token)
    except ValueError:
        return VerifyResponse(authenticated=False)

    sub = payload.get("sub")
    if not sub:
        return VerifyResponse(authenticated=False)

    user = await session.get(User, int(sub))
    if not user or user.status != UserStatus.ACTIVE:
        return VerifyResponse(authenticated=False)

    return VerifyResponse(
        authenticated=True,
        user_id=user.id,
        username=user.username,
        is_admin=user.role == UserRole.ADMIN,
        account_limit=user.account_limit,
    )


@router.post("/logout", response_model=ApiResponse)
async def logout_user() -> ApiResponse:
    return ApiResponse(success=True, message="已退出登录")


@router.post("/refresh", response_model=LoginResponse)
async def refresh_token(
    request: Request,
    session: AsyncSession = Depends(deps.get_db_session),
    auth_service: AuthService = Depends(deps.get_auth_service),
) -> LoginResponse:
    """刷新访问令牌"""
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        return LoginResponse(success=False, message="未提供刷新令牌")

    refresh_token = auth_header.split(" ", 1)[1]
    try:
        payload = decode_token(refresh_token)
    except ValueError:
        return LoginResponse(success=False, message="刷新令牌无效")

    # 验证是否为refresh token
    if payload.get("type") != "refresh":
        return LoginResponse(success=False, message="令牌类型错误")

    sub = payload.get("sub")
    if not sub:
        return LoginResponse(success=False, message="刷新令牌无效")

    user = await session.get(User, int(sub))
    if not user or user.status != UserStatus.ACTIVE:
        return LoginResponse(success=False, message="用户不存在或已被禁用")

    # 生成新的access token和refresh token
    return LoginResponse(
        success=True,
        message="令牌刷新成功",
        token=auth_service.create_access_token(user),
        refresh_token=auth_service.create_refresh_token(user),
        user_id=user.id,
        username=user.username,
        is_admin=user.role == UserRole.ADMIN,
        account_limit=user.account_limit,
    )


@router.get("/check-default-password", response_model=ApiResponse)
async def check_default_password(
    current_user: User = Depends(deps.get_current_admin_user),
    auth_service: AuthService = Depends(deps.get_auth_service),
) -> ApiResponse:
    """
    检查管理员密码是否为默认值（admin123）
    仅管理员可调用，返回 data.is_default 表示是否为默认密码
    """
    is_default = auth_service._verify_user_password(current_user, "admin123")
    return ApiResponse(
        success=True,
        message="检查完成",
        data={"is_default": is_default},
    )


@router.post("/register", response_model=ApiResponse, status_code=status.HTTP_201_CREATED)
async def register_user(
    payload: UserCreate,
    user_service: UserService = Depends(deps.get_user_service),
) -> ApiResponse:
    # 验证邮箱验证码
    if payload.email and payload.verification_code:
        code_valid, code_msg = check_email_code(payload.email, payload.verification_code, "register")
        if not code_valid:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=code_msg)
    elif payload.email:
        # 有邮箱但没有验证码
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="请输入邮箱验证码")
    
    # 检查用户名是否已存在
    existing = await user_service.get_by_username(payload.username)
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="用户名已被注册")
    
    # 检查邮箱是否已存在
    if payload.email:
        existing_email = await user_service.get_by_email(payload.email)
        if existing_email:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="邮箱已被注册")
    
    await user_service.create(payload)
    return ApiResponse(success=True, message="注册成功")


@router.post("/reset-password", response_model=ApiResponse)
async def reset_password(
    payload: ResetPasswordRequest,
    session: AsyncSession = Depends(deps.get_db_session),
) -> ApiResponse:
    """重置密码（通过邮箱验证码）

    业务错误统一以 HTTP 200 + success=False 返回，由前端展示具体消息。
    """
    # 先校验新密码长度，避免在密码不合规时提前消费掉验证码
    if len(payload.new_password) < 6:
        return ApiResponse(success=False, message="新密码长度不能少于6位")

    # 验证邮箱验证码（校验成功后会消费该验证码）
    code_valid, code_msg = check_email_code(payload.email, payload.verification_code, "reset_password")
    if not code_valid:
        return ApiResponse(success=False, message=code_msg)

    # 查找用户
    user_service = UserService(session)
    user = await user_service.get_by_email(payload.email)
    if not user:
        return ApiResponse(success=False, message="该邮箱未注册")

    # 更新密码（直接操作 ORM 对象后 commit）
    user.password_hash = get_password_hash(payload.new_password)
    await session.commit()

    return ApiResponse(success=True, message="密码重置成功")
