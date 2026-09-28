import json

from common.utils.response_field import (
    RESPONSE_FIELD_EMPTY_MESSAGE,
    extract_card_api_response_content,
    is_local_baidu_share_api,
    render_local_baidu_share_template,
)


def test_local_baidu_share_template_is_rendered():
    response = json.dumps({
        "code": 0,
        "data": {"link": "https://pan.baidu.com/s/example", "pwd": "abcd"},
    })
    assert render_local_baidu_share_template(
        response,
        "老板，任天堂下载：{{data.link}} 密码{{data.pwd}}",
    ) == "老板，任天堂下载：https://pan.baidu.com/s/example 密码abcd"


def test_local_baidu_share_api_requires_exact_host_and_path():
    assert is_local_baidu_share_api("http://192.168.11.131:18888/api/v1/shares")
    assert not is_local_baidu_share_api("http://192.168.11.132:18888/api/v1/shares")
    assert not is_local_baidu_share_api("http://192.168.11.131:18888/api/v1/share")


def test_other_api_keeps_original_response_field_behavior():
    response = '{"data":{"link":"https://example.test","pwd":"abcd"}}'
    assert extract_card_api_response_content(response, "data.link") == "https://example.test"
    assert render_local_baidu_share_template(response, "{{data.missing}}") == RESPONSE_FIELD_EMPTY_MESSAGE
