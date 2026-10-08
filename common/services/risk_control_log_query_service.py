"""
风控日志处理中状态查询服务。

功能：
1. 按账号判断是否已有处理中的风控任务
2. 查询失败时返回明确原因，由调用方按保守策略跳过重复处理
3. 数据库连接异常时自动重试
"""
from __future__ import annotations

import asyncio
from datetime import timedelta
from dataclasses import dataclass

from sqlalchemy import exists, func, select, update

from common.db.session import async_session_maker
from common.models.risk_control_log import XYRiskControlLog
from common.utils.time_utils import get_beijing_now_naive


# 滑块验证属于人工/浏览器流程，正常也不应长期占用账号。
# 超过该时间视为孤儿任务，下一次刷新时自动收尾，避免账号永久被挡住。
PROCESSING_RISK_CONTROL_MAX_AGE = timedelta(minutes=20)
STALE_RISK_CONTROL_RESULT = "风控验证超过20分钟未完成，系统已自动结束本次任务"
STALE_RISK_CONTROL_ERROR = "风控任务超时，已释放账号验证状态"


_ACCOUNT_RISK_CONTROL_LOCKS: dict[str, asyncio.Lock] = {}


def get_account_risk_control_lock(account_identifier: str) -> asyncio.Lock:
    """获取进程内账号级风控抢占锁。

    查询处理中状态和创建 processing 日志必须在同一把锁内完成，避免同一
    WebSocket 进程中的两个协程同时通过检查。

    Args:
        account_identifier: 账号业务标识。
    Returns:
        当前进程内该账号共用的异步锁。
    """
    clean_identifier = str(account_identifier or "").strip() or "__empty__"
    lock = _ACCOUNT_RISK_CONTROL_LOCKS.get(clean_identifier)
    if lock is None:
        lock = asyncio.Lock()
        _ACCOUNT_RISK_CONTROL_LOCKS[clean_identifier] = lock
    return lock


@dataclass(frozen=True, slots=True)
class ProcessingRiskControlCheckResult:
    """账号处理中风控日志检查结果。"""

    success: bool
    has_processing: bool
    message: str = ""


async def check_account_processing_risk_control_log(
    account_identifier: str,
    *,
    max_attempts: int = 3,
    retry_delay_seconds: float = 0.5,
) -> ProcessingRiskControlCheckResult:
    """检查指定账号是否已有处理中的风控日志。

    Args:
        account_identifier: 账号业务标识，对应风控日志 account_identifier。
        max_attempts: 数据库查询最大尝试次数。
        retry_delay_seconds: 相邻重试之间的等待秒数。
    Returns:
        查询成功时返回实际占用状态；查询失败时按保守策略返回占用。
    """
    clean_identifier = str(account_identifier or "").strip()
    if not clean_identifier:
        return ProcessingRiskControlCheckResult(
            False,
            True,
            "账号标识为空，无法检查处理中风控日志",
        )

    attempts = max(1, int(max_attempts))
    last_error = ""
    for attempt in range(1, attempts + 1):
        try:
            async with async_session_maker() as session:
                # 只清理当前账号的过期 processing 记录，不影响其它账号。
                # 这样即使 WebSocket 没有重启，也能从一次新的刷新请求中自愈。
                stale_cutoff = get_beijing_now_naive() - PROCESSING_RISK_CONTROL_MAX_AGE
                await session.execute(
                    update(XYRiskControlLog)
                    .where(
                        XYRiskControlLog.account_identifier == clean_identifier,
                        XYRiskControlLog.processing_status == "processing",
                        # updated_at is the authoritative heartbeat for a task.
                        # A task may be created early and legitimately continue;
                        # only a task with no update for the timeout is orphaned.
                        func.coalesce(
                            XYRiskControlLog.updated_at,
                            XYRiskControlLog.created_at,
                        ) < stale_cutoff,
                    )
                    .values(
                        processing_status="failed",
                        processing_result=STALE_RISK_CONTROL_RESULT,
                        error_message=STALE_RISK_CONTROL_ERROR,
                        updated_at=get_beijing_now_naive(),
                    )
                )
                await session.commit()
                has_processing = bool(
                    (
                        await session.execute(
                            select(
                                exists().where(
                                    XYRiskControlLog.account_identifier
                                    == clean_identifier,
                                    XYRiskControlLog.processing_status == "processing",
                                )
                            )
                        )
                    ).scalar()
                )
            return ProcessingRiskControlCheckResult(
                True,
                has_processing,
                (
                    "账号已有处理中的风控任务"
                    if has_processing
                    else "账号当前没有处理中的风控任务"
                ),
            )
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            if attempt < attempts:
                await asyncio.sleep(max(0.0, retry_delay_seconds))

    return ProcessingRiskControlCheckResult(
        False,
        True,
        f"查询处理中风控日志失败，已重试{attempts}次：{last_error}",
    )


async def cleanup_stale_processing_risk_control_logs(
    *,
    max_attempts: int = 3,
    retry_delay_seconds: float = 0.5,
) -> int:
    """结束所有长时间没有更新的处理中风控任务。

    这是一个账号隔离的后台兜底清理：只更新超时的 ``processing`` 行，
    不触碰成功、失败、取消或其它账号的活动记录。
    """
    stale_cutoff = get_beijing_now_naive() - PROCESSING_RISK_CONTROL_MAX_AGE
    attempts = max(1, int(max_attempts))
    for attempt in range(1, attempts + 1):
        try:
            async with async_session_maker() as session:
                result = await session.execute(
                    update(XYRiskControlLog)
                    .where(
                        XYRiskControlLog.processing_status == "processing",
                        func.coalesce(
                            XYRiskControlLog.updated_at,
                            XYRiskControlLog.created_at,
                        ) < stale_cutoff,
                    )
                    .values(
                        processing_status="failed",
                        processing_result=STALE_RISK_CONTROL_RESULT,
                        error_message=STALE_RISK_CONTROL_ERROR,
                        updated_at=get_beijing_now_naive(),
                    )
                )
                await session.commit()
                return int(result.rowcount or 0)
        except Exception as exc:
            if attempt >= attempts:
                raise
            await asyncio.sleep(max(0.0, retry_delay_seconds))
    return 0
