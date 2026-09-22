from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _read(relative_path: str) -> str:
    return (PROJECT_ROOT / relative_path).read_text(encoding="utf-8")


def test_websocket_realtime_rate_uses_account_proxy() -> None:
    source = _read("websocket/app/services/xianyu/xianyu_async.py")

    assert "proxy_url = self._get_proxy_url()" in source
    assert "RateService(\n                self.cookies_str,\n                account_id=self.cookie_id,\n                proxy_url=proxy_url," in source
    assert "已阻止直连自动评价" in source


def test_backend_batch_rate_uses_account_proxy() -> None:
    source = _read("backend-web/app/api/routes/auto_rate.py")

    assert "proxy_url = build_account_proxy_url(" in source
    assert "fetch_merchant_rate_list(" in source
    assert "proxy_url=proxy_url" in source
    assert "已阻止直连批量补评价" in source


def test_buyer_credit_rule_accepts_proxy_url() -> None:
    source = _read("websocket/app/services/xianyu/delivery_rules/buyer_credit_rule.py")

    assert "proxy_url: str | None = None" in source
    assert "build_aiohttp_proxy_options(proxy_url)" in source
    assert "proxy=request_proxy" in source
