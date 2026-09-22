import asyncio

from common.services.cookie_renew_api_service import CookieRenewApiService
from common.utils.account_proxy import build_account_proxy_url


def test_account_proxy_url_strips_auth_whitespace():
    proxy_url = build_account_proxy_url(
        "socks5",
        "proxy.example.com",
        1080,
        "  user1  ",
        "\t secret-pass \n",
        True,
    )

    assert proxy_url == "socks5://user1:secret-pass@proxy.example.com:1080"


def test_cookie_renew_api_uses_aiohttp_request_proxy_for_http_proxy():
    async def run_check():
        service = CookieRenewApiService()

        session_kwargs, request_kwargs = service._build_http_proxy_options(
            "http://user:pass@proxy.example.com:8080"
        )

        assert "connector" not in session_kwargs
        assert request_kwargs == {"proxy": "http://user:pass@proxy.example.com:8080"}

    asyncio.run(run_check())
