"""A login with no Basecamp 3/4 account must get a plain, actionable message everywhere.

Launchpad's authorization.json lists every 37signals product the login can reach
(``{"identity": {...}, "accounts": [{"product": "bc3", "id": ..., "name": ...}]}``).
A login with no Basecamp at all gets ``"accounts": []``; one that only uses older
products gets entries such as ``"bcx"`` (Basecamp 2) but no ``"bc3"``.
"""

import importlib
import os
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

# Imported up front: some of these load a .env at import time, which must not
# leak a BASECAMP_ACCOUNT_ID past the fixture below.
import auth_manager  # noqa: F401
import basecamp_fastmcp  # noqa: F401
import sign_in_messages
import token_storage  # noqa: F401
from basecamp_mcp_server import cli

LOGIN = "uvx basecamp-mcp-server login"
EMPTY = {"identity": {"email_address": "pat@example.com"}, "accounts": []}
OLD_ONLY = {
    "identity": {"email_address": "pat@example.com"},
    "accounts": [{"id": 1, "product": "bcx", "name": "Old"}, {"id": 2, "product": "campfire"}],
}


@pytest.fixture(autouse=True)
def _restore_environment(monkeypatch):
    saved = dict(os.environ)
    monkeypatch.setenv("BASECAMP_MCP_LOGIN_COMMAND", LOGIN)
    monkeypatch.delenv("BASECAMP_ACCOUNT_ID", raising=False)
    yield
    os.environ.clear()
    os.environ.update(saved)


def _assert_actionable(message):
    assert "Basecamp 3 or 4" in message
    assert "sign out" in message and LOGIN in message
    assert "Traceback" not in message


@pytest.mark.parametrize("identity", [EMPTY, OLD_ONLY])
def test_login_explains_a_login_with_no_basecamp_account(identity):
    with pytest.raises(cli.LoginError) as failure:
        cli.choose_account(identity, None, interactive=True)
    message = str(failure.value)
    _assert_actionable(message)
    assert "pat@example.com" in message
    assert "basecamp.com" in message


def test_login_names_other_products_in_plain_words():
    message = sign_in_messages.no_basecamp_account(OLD_ONLY)
    assert "Basecamp 2" in message and "Campfire" in message
    assert "bcx" not in message


def test_requested_account_id_does_not_hide_the_real_problem():
    with pytest.raises(cli.LoginError, match="isn't a member of any Basecamp 3 or 4 account"):
        cli.choose_account(EMPTY, "123", interactive=False)


def _status(monkeypatch, tmp_path, token, identity=None, offline=False):
    monkeypatch.setenv("BASECAMP_MCP_HOME", str(tmp_path))
    # The account check uses only the token: no app client ID/secret needed.
    monkeypatch.delenv("BASECAMP_CLIENT_ID", raising=False)
    monkeypatch.delenv("BASECAMP_CLIENT_SECRET", raising=False)
    import auth_manager
    import basecamp_oauth
    import token_storage

    monkeypatch.setattr(token_storage, "get_token", lambda: token)
    monkeypatch.setattr(auth_manager, "ensure_authenticated", lambda: True)
    monkeypatch.setattr(basecamp_oauth, "fetch_identity", lambda _t, _ua=None, timeout=None: identity)
    return cli.status(SimpleNamespace(offline=offline))


@pytest.mark.parametrize("offline", [True, False])
def test_status_flags_a_token_with_no_account(monkeypatch, tmp_path, capsys, offline):
    token = {"access_token": "t", "account_id": None, "expires_at": "later"}
    assert _status(monkeypatch, tmp_path, token, offline=offline) == 1
    out = capsys.readouterr().out
    assert "no Basecamp account is selected" in out
    _assert_actionable(out)


def test_status_flags_a_login_that_lost_its_only_account(monkeypatch, tmp_path, capsys):
    token = {"access_token": "t", "account_id": "999", "expires_at": "later"}
    assert _status(monkeypatch, tmp_path, token, identity=EMPTY) == 1
    _assert_actionable(capsys.readouterr().out)


def test_status_lists_remaining_accounts_when_saved_one_is_gone(monkeypatch, tmp_path, capsys):
    token = {"access_token": "t", "account_id": "999", "expires_at": "later"}
    identity = {"accounts": [{"id": 7, "product": "bc3", "name": "Team"}]}
    assert _status(monkeypatch, tmp_path, token, identity=identity) == 1
    out = capsys.readouterr().out
    assert "can no longer open Basecamp account 999" in out
    assert "Team (id 7)" in out and LOGIN in out


def test_status_still_checks_the_connection_when_the_account_list_is_unreachable(
    monkeypatch, tmp_path, capsys
):
    import basecamp_client
    import basecamp_oauth

    def unreachable(_token, _user_agent=None, timeout=None):
        raise Exception("Failed to get identity: HTTP 503")

    profile = Mock(status_code=200, json=Mock(return_value={"name": "Pat"}))
    monkeypatch.setattr(basecamp_client.BasecampClient, "get", lambda self, _path: profile)
    token = {"access_token": "t", "account_id": "7", "expires_at": "later"}
    monkeypatch.setattr(basecamp_oauth, "fetch_identity", unreachable)
    monkeypatch.setenv("BASECAMP_MCP_HOME", str(tmp_path))
    monkeypatch.setenv("BASECAMP_CLIENT_ID", "id")
    monkeypatch.setenv("BASECAMP_CLIENT_SECRET", "secret")
    import auth_manager
    import token_storage

    monkeypatch.setattr(token_storage, "get_token", lambda: token)
    monkeypatch.setattr(auth_manager, "ensure_authenticated", lambda: True)

    assert cli.status(SimpleNamespace(offline=False)) == 0
    out = capsys.readouterr().out
    assert "Warning" in out and "Connection check: OK" in out


def test_mcp_tools_explain_a_token_with_no_account(monkeypatch):
    import basecamp_fastmcp
    import token_storage

    monkeypatch.setenv("USER_AGENT", "test-agent")
    monkeypatch.setattr(token_storage, "get_token", lambda: {"access_token": "t", "account_id": None})
    monkeypatch.setattr(token_storage, "is_token_expired", lambda: False)
    response = basecamp_fastmcp._get_auth_error_response()
    assert response["error"] == "No Basecamp account"
    _assert_actionable(response["message"])


def test_auth_problem_keeps_expired_and_signed_out_cases():
    assert sign_in_messages.auth_problem(None, False)[0] == "Authentication required"
    assert sign_in_messages.auth_problem({"access_token": "t"}, True)[0] == "OAuth token expired"
    assert sign_in_messages.auth_problem({"access_token": "t", "account_id": "1"}, False)[0] == (
        "Authentication required"
    )


def test_web_sign_in_shows_the_message_and_saves_no_token(monkeypatch):
    monkeypatch.delenv("BASECAMP_MCP_LOGIN_COMMAND")
    for name in ("BASECAMP_CLIENT_ID", "BASECAMP_CLIENT_SECRET", "BASECAMP_REDIRECT_URI", "USER_AGENT"):
        monkeypatch.setenv(name, "test-value")
    oauth_app = importlib.import_module("oauth_app")
    monkeypatch.delenv("BASECAMP_ACCOUNT_ID", raising=False)  # its import may load a .env
    oauth = Mock(
        exchange_code_for_token=Mock(return_value={"access_token": "t", "refresh_token": "r"}),
        get_identity=Mock(return_value=EMPTY),
    )
    monkeypatch.setattr(oauth_app, "get_oauth_client", Mock(return_value=oauth))
    store = Mock(return_value=True)
    monkeypatch.setattr(oauth_app.token_storage, "store_token", store)

    response = oauth_app.app.test_client().get("/auth/callback?code=abc")

    page = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "No Basecamp account" in page and "isn&#39;t a member of any Basecamp 3 or 4 account" in page
    assert "localhost:8000" in page
    store.assert_not_called()
