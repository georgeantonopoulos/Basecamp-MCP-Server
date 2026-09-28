"""OAuth failures must not expose provider payloads or callback parameters in logs."""

import importlib
import logging
import threading
from urllib.request import urlopen
from unittest.mock import Mock

import pytest

import basecamp_oauth
from werkzeug.serving import make_server


@pytest.mark.parametrize(
    "method,args,request_method",
    [
        ("exchange_code_for_token", ("authorization-code",), "post"),
        ("refresh_token", ("refresh-token",), "post"),
        ("get_identity", ("access-token",), "get"),
    ],
)
def test_oauth_provider_errors_exclude_response_body(
    monkeypatch, method, args, request_method
):
    secret = "sensitive-provider-response"
    response = Mock(status_code=400, text=secret)
    monkeypatch.setattr(basecamp_oauth.requests, request_method, Mock(return_value=response))
    client = basecamp_oauth.BasecampOAuth(
        client_id="client", client_secret="secret",
        redirect_uri="http://localhost/callback", user_agent="test-agent",
    )

    with pytest.raises(Exception, match="HTTP 400") as failure:
        getattr(client, method)(*args)

    assert secret not in str(failure.value)


def test_callback_does_not_log_external_error_or_provider_body(monkeypatch, caplog):
    for name in ("BASECAMP_CLIENT_ID", "BASECAMP_CLIENT_SECRET", "BASECAMP_REDIRECT_URI", "USER_AGENT"):
        monkeypatch.setenv(name, "test-value")
    oauth_app = importlib.import_module("oauth_app")
    client = oauth_app.app.test_client()

    with caplog.at_level(logging.ERROR, logger=oauth_app.__name__):
        response = client.get("/auth/callback?error=sensitive-callback-value")
        assert response.status_code == 200
        assert "sensitive-callback-value" not in caplog.text

        caplog.clear()
        monkeypatch.setattr(
            oauth_app, "get_oauth_client",
            Mock(return_value=Mock(exchange_code_for_token=Mock(
                side_effect=Exception("Failed to exchange code for token: HTTP 400")
            ))),
        )
        response = client.get("/auth/callback?code=authorization-code")
        assert response.status_code == 200
        assert "authorization-code" not in caplog.text
        assert "HTTP 400" in caplog.text


def test_real_http_access_log_omits_callback_query(monkeypatch, caplog):
    for name in ("BASECAMP_CLIENT_ID", "BASECAMP_CLIENT_SECRET", "BASECAMP_REDIRECT_URI", "USER_AGENT"):
        monkeypatch.setenv(name, "test-value")
    oauth_app = importlib.import_module("oauth_app")
    monkeypatch.setattr(oauth_app, "get_oauth_client", Mock(side_effect=Exception("test failure")))
    server = make_server(
        "127.0.0.1", 0, oauth_app.app,
        request_handler=oauth_app.QueryFreeRequestHandler,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with caplog.at_level(logging.INFO, logger="werkzeug"):
            with urlopen(
                f"http://127.0.0.1:{server.server_port}/auth/callback?code=private-code",
                timeout=5,
            ) as response:
                assert response.status == 200
        assert 'GET /auth/callback HTTP/' in caplog.text
        assert "private-code" not in caplog.text
        assert "?code=" not in caplog.text
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()
