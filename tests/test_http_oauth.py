"""Remote HTTP sign-in mode: every MCP user gets their own Basecamp token."""

import base64
import hashlib
import json
import secrets
import time
from urllib.parse import parse_qs, urlsplit

import pytest
from starlette.testclient import TestClient

import basecamp_fastmcp
from basecamp_mcp_server import http_server, oauth_provider

BASE = "http://localhost:8765"
CLIENT_REDIRECT = "http://localhost:9999/callback"
MCP_HEADERS = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}


class FakeBasecamp:
    """Stands in for 37signals Launchpad. Each code belongs to one person."""

    def __init__(self):
        self.people = {}
        self.refreshed = []

    def add_person(self, code, person_id, accounts, expires_in=1209600):
        self.people[code] = (person_id, accounts, expires_in)

    def get_authorization_url(self, state=None):
        return f"https://launchpad.example/authorization/new?state={state}"

    def exchange_code_for_token(self, code):
        person_id, _, expires_in = self.people[code]
        return {"access_token": f"bc-{person_id}", "refresh_token": f"bc-refresh-{person_id}", "expires_in": expires_in}

    def get_identity(self, access_token):
        person_id = access_token.removeprefix("bc-")
        accounts = next(a for p, a, _ in self.people.values() if p == person_id)
        return {
            "identity": {"id": person_id, "first_name": person_id},
            "accounts": [{"product": "bc3", "id": a, "name": f"Account {a}"} for a in accounts],
        }

    def refresh_token(self, refresh_token):
        self.refreshed.append(refresh_token)
        return {"access_token": refresh_token.replace("refresh", "renewed"), "expires_in": 1209600}


def _tool_server():
    from mcp.server.fastmcp import FastMCP

    server = FastMCP("t")

    @server.tool()
    def whoami() -> str:
        """Return the Basecamp credentials this call would use."""
        return json.dumps(basecamp_fastmcp._credential_resolver())

    return server


@pytest.fixture
def setup(tmp_path):
    fake = FakeBasecamp()
    provider = oauth_provider.BasecampOAuthProvider(tmp_path, f"{BASE}/auth/callback", basecamp_oauth=fake)
    app = http_server.build_oauth_app(_tool_server(), provider, BASE, "127.0.0.1")
    with TestClient(app, base_url=BASE, follow_redirects=False) as client:
        yield client, fake, provider, tmp_path
    basecamp_fastmcp.set_credential_resolver(None)


def _sign_in(client, basecamp_code, account=None):
    """Run the whole connector flow; return the token response."""
    reg = client.post(
        "/register",
        json={"redirect_uris": [CLIENT_REDIRECT], "token_endpoint_auth_method": "none", "client_name": "t"},
    )
    assert reg.status_code == 201, reg.text
    client_id = reg.json()["client_id"]
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    auth = client.get(
        "/authorize",
        params={
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": CLIENT_REDIRECT,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "state": "client-state",
        },
    )
    assert auth.status_code == 302, auth.text
    to_basecamp = urlsplit(auth.headers["location"])
    assert to_basecamp.netloc == "launchpad.example"
    state = parse_qs(to_basecamp.query)["state"][0]

    back = client.get("/auth/callback", params={"code": basecamp_code, "state": state})
    if account is not None:
        assert back.status_code == 200 and "Choose a Basecamp account" in back.text
        back = client.get("/auth/callback/account", params={"state": state, "account": account})
    assert back.status_code == 302, back.text
    to_client = urlsplit(back.headers["location"])
    query = parse_qs(to_client.query)
    assert f"{to_client.scheme}://{to_client.netloc}{to_client.path}" == CLIENT_REDIRECT
    assert query["state"] == ["client-state"]

    token = client.post(
        "/token",
        data={
            "grant_type": "authorization_code",
            "code": query["code"][0],
            "redirect_uri": CLIENT_REDIRECT,
            "client_id": client_id,
            "code_verifier": verifier,
        },
    )
    assert token.status_code == 200, token.text
    return {**token.json(), "client_id": client_id}


def _whoami(client, access_token):
    headers = {**MCP_HEADERS, "Authorization": f"Bearer {access_token}"}
    init = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}},
        },
        headers=headers,
    )
    assert init.status_code == 200, init.text
    headers["mcp-session-id"] = init.headers["mcp-session-id"]
    client.post("/mcp", json={"jsonrpc": "2.0", "method": "notifications/initialized"}, headers=headers)
    call = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "whoami", "arguments": {}}},
        headers=headers,
    )
    assert call.status_code == 200, call.text
    data = next(line for line in call.text.splitlines() if line.startswith("data:"))
    return json.loads(json.loads(data[5:])["result"]["content"][0]["text"])


def test_unauthenticated_requests_point_to_the_sign_in(setup):
    client, *_ = setup
    response = client.post("/mcp", json={}, headers=MCP_HEADERS)
    assert response.status_code == 401
    assert "oauth-protected-resource" in response.headers["www-authenticate"]
    meta = client.get("/.well-known/oauth-authorization-server").json()
    assert meta["registration_endpoint"] == f"{BASE}/register"


def test_two_users_each_get_their_own_basecamp(setup):
    client, fake, *_ = setup
    fake.add_person("code-ann", "ann", ["111"])
    fake.add_person("code-bob", "bob", ["222"])
    ann = _sign_in(client, "code-ann")
    bob = _sign_in(client, "code-bob")
    assert _whoami(client, ann["access_token"]) == {"access_token": "bc-ann", "account_id": "111"}
    assert _whoami(client, bob["access_token"]) == {"access_token": "bc-bob", "account_id": "222"}


def test_user_with_several_accounts_chooses_one(setup):
    client, fake, *_ = setup
    fake.add_person("code-cat", "cat", ["333", "444"])
    cat = _sign_in(client, "code-cat", account="444")
    assert _whoami(client, cat["access_token"])["account_id"] == "444"


def test_codes_and_refresh_tokens_work_once(setup):
    client, fake, *_ = setup
    fake.add_person("code-ann", "ann", ["111"])
    ann = _sign_in(client, "code-ann")
    form = {"grant_type": "refresh_token", "refresh_token": ann["refresh_token"], "client_id": ann["client_id"]}
    first = client.post("/token", data=form)
    assert first.status_code == 200, first.text
    assert client.post("/token", data=form).status_code == 400
    assert _whoami(client, first.json()["access_token"])["access_token"] == "bc-ann"


def test_tokens_are_stored_hashed_and_private(setup):
    client, fake, provider, home = setup
    fake.add_person("code-ann", "ann", ["111"])
    ann = _sign_in(client, "code-ann")
    stored = (home / oauth_provider.STORE_NAME).read_text()
    assert ann["access_token"] not in stored and ann["refresh_token"] not in stored
    assert oct((home / oauth_provider.STORE_NAME).stat().st_mode & 0o777) == "0o600"
    # A restart keeps the sign-in.
    again = oauth_provider.BasecampOAuthProvider(home, f"{BASE}/auth/callback", basecamp_oauth=fake)
    import anyio

    assert anyio.run(again.load_access_token, ann["access_token"]).user_key == "ann:111"


def test_expiring_basecamp_token_is_refreshed(setup):
    client, fake, *_ = setup
    fake.add_person("code-ann", "ann", ["111"], expires_in=60)
    ann = _sign_in(client, "code-ann")
    assert _whoami(client, ann["access_token"])["access_token"] == "bc-renewed-ann"
    assert fake.refreshed == ["bc-refresh-ann"]


def test_forged_state_and_wrong_token_are_refused(setup):
    client, fake, *_ = setup
    fake.add_person("code-ann", "ann", ["111"])
    assert client.get("/auth/callback", params={"code": "code-ann", "state": "made-up"}).status_code == 400
    response = client.post("/mcp", json={}, headers={**MCP_HEADERS, "Authorization": "Bearer nope"})
    assert response.status_code == 401


def test_no_shared_token_fallback(setup, monkeypatch):
    import token_storage

    monkeypatch.setattr(token_storage, "get_token", lambda: {"access_token": "shared", "account_id": "1"})
    monkeypatch.setenv("USER_AGENT", "t")
    # Outside an authenticated request there is no user, so no client, and never the shared token.
    assert basecamp_fastmcp._get_basecamp_client() is None
    assert basecamp_fastmcp._get_auth_error_response()["error"] == "Basecamp sign-in required"
