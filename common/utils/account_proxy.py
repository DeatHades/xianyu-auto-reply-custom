"""账号级代理的最小公共工具。

只负责把已保存的账号代理配置转换为单次请求可用的代理信息；不保存任何
全局状态，也不提供直连回退，避免一个账号的代理影响另一个账号。
"""
from __future__ import annotations

import re
from urllib.parse import quote


class AccountProxyConfigurationError(ValueError):
    """账号已启用代理，但配置或运行依赖不可用。"""


_HOST_RE = re.compile(r"^[A-Za-z0-9.-]+$|^\[[0-9A-Fa-f:.]+\]$")
_PROXY_TYPES = {"http", "https", "socks5"}


def build_account_proxy_url(
    proxy_type: str | None,
    proxy_host: str | None,
    proxy_port: int | None,
    proxy_user: str | None = None,
    proxy_pass: str | None = None,
) -> str | None:
    """构造单账号代理 URL；未启用时返回 ``None``。

    已启用代理的配置不完整或非法时直接抛错，由调用方停止该账号动作，
    而不是尝试使用主机真实出口 IP。
    """
    proxy_type = (proxy_type or "none").lower().strip()
    if proxy_type == "none":
        return None
    if proxy_type not in _PROXY_TYPES:
        raise AccountProxyConfigurationError(f"不支持的代理类型: {proxy_type}")

    host = (proxy_host or "").strip()
    if not host or not _HOST_RE.fullmatch(host):
        raise AccountProxyConfigurationError("代理主机格式无效")
    if not isinstance(proxy_port, int) or not 1 <= proxy_port <= 65535:
        raise AccountProxyConfigurationError("代理端口无效")

    username = (proxy_user or "").strip()
    password = proxy_pass or ""
    if bool(username) != bool(password):
        raise AccountProxyConfigurationError("代理用户名和密码必须同时填写")

    auth = ""
    if username:
        auth = f"{quote(username, safe='')}:{quote(password, safe='')}@"
    return f"{proxy_type}://{auth}{host}:{proxy_port}"


def build_aiohttp_proxy_options(proxy_url: str | None) -> tuple[object | None, str | None]:
    """返回 ``(connector, request_proxy)``，供单次 aiohttp 会话使用。

    HTTP/HTTPS 代理使用 aiohttp 原生的请求级 ``proxy``；SOCKS5 使用
    ``aiohttp-socks`` connector。SOCKS 依赖不可用时抛错，禁止直连回退。
    """
    if not proxy_url:
        return None, None
    if proxy_url.startswith(("http://", "https://")):
        return None, proxy_url
    if proxy_url.startswith("socks5://"):
        try:
            from aiohttp_socks import ProxyConnector
        except ImportError as exc:
            raise AccountProxyConfigurationError("SOCKS5 代理依赖 aiohttp-socks 未安装") from exc
        return ProxyConnector.from_url(proxy_url, rdns=True), None
    raise AccountProxyConfigurationError("代理地址格式无效")
