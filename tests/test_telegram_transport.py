import json
import httpx
import pytest
from platform_app.telegram import BotClient, TelegramError
from platform_app.errors import RetryLater


def test_transport_uses_current_method_and_parameter_contract():
    def handler(request):
        assert request.url.path.endswith("/getManagedBotToken")
        assert json.loads(request.content) == {"user_id": 700001}
        return httpx.Response(200, json={"ok": True, "result": "700001:private-value"})

    client = BotClient("100001:never-log-this-token", transport=httpx.MockTransport(handler))
    assert client.call("getManagedBotToken", user_id=700001) == "700001:private-value"
    assert "never-log" not in repr(client)


def test_telegram_retry_after_is_respected():
    client = BotClient(
        "100001:token",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                429, json={"ok": False, "error_code": 429, "parameters": {"retry_after": 17}}
            )
        ),
    )
    with pytest.raises(RetryLater) as error:
        client.call("sendMessage", chat_id=1, text="Hi")
    assert error.value.seconds == 17


def test_transport_error_never_contains_credentials_or_provider_description():
    client = BotClient(
        "100001:private-value",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                401, json={"ok": False, "error_code": 401, "description": "100001:private-value"}
            )
        ),
    )
    with pytest.raises(TelegramError) as error:
        client.call("getMe")
    assert error.value.code == "TOKEN_INVALID" and "private-value" not in str(error.value)
