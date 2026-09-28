"""Tests that OAuth network calls have bounded timeouts."""

from unittest.mock import MagicMock, patch

from basecamp_client import DEFAULT_REQUEST_TIMEOUT
from basecamp_oauth import BasecampOAuth


def _oauth():
    return BasecampOAuth(
        client_id="client",
        client_secret="secret",
        redirect_uri="http://localhost/callback",
        user_agent="Test App (test@example.com)",
    )


def test_oauth_exchange_uses_timeout():
    response = MagicMock(status_code=200)
    response.json.return_value = {"access_token": "token"}
    with patch("basecamp_oauth.requests.post", return_value=response) as post:
        assert _oauth().exchange_code_for_token("code")["access_token"] == "token"
    assert post.call_args.kwargs["timeout"] == DEFAULT_REQUEST_TIMEOUT


def test_oauth_refresh_uses_timeout():
    response = MagicMock(status_code=200)
    response.json.return_value = {"access_token": "new-token"}
    with patch("basecamp_oauth.requests.post", return_value=response) as post:
        assert _oauth().refresh_token("refresh")["access_token"] == "new-token"
    assert post.call_args.kwargs["timeout"] == DEFAULT_REQUEST_TIMEOUT


def test_oauth_identity_lookup_uses_timeout():
    response = MagicMock(status_code=200)
    response.json.return_value = {"identity": {"id": 1}}
    with patch("basecamp_oauth.requests.get", return_value=response) as get:
        assert _oauth().get_identity("token")["identity"]["id"] == 1
    assert get.call_args.kwargs["timeout"] == DEFAULT_REQUEST_TIMEOUT
