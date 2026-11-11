"""Remote HTTP mode: the access key guards every request and MCP works through it."""

import os

import pytest
from starlette.testclient import TestClient

from basecamp_mcp_server import cli, http_server

TOKEN = "k" * 43
INIT = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}},
}
HEADERS = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}


@pytest.fixture(autouse=True)
def _restore_environment():
    saved = dict(os.environ)
    yield
    os.environ.clear()
    os.environ.update(saved)


def _fresh_server():
    from mcp.server.fastmcp import FastMCP

    server = FastMCP("t")

    @server.tool()
    def ping() -> str:
        return "pong"

    return server


def _client(host="127.0.0.1"):
    app = http_server.build_app(_fresh_server(), TOKEN, host)
    return TestClient(app, base_url=f"http://{'localhost' if host == '127.0.0.1' else 'example.test'}:8765")


@pytest.mark.parametrize("auth", [None, "Bearer wrong", f"bearer {TOKEN}", TOKEN, f"Bearer {TOKEN}x"])
def test_requests_without_the_right_key_are_refused(auth):
    headers = dict(HEADERS)
    if auth:
        headers["Authorization"] = auth
    with _client() as client:
        response = client.post("/mcp", json=INIT, headers=headers)
    assert response.status_code == 401
    assert response.headers["www-authenticate"].startswith("Bearer")


def test_other_paths_are_also_guarded():
    with _client() as client:
        assert client.get("/").status_code == 401


@pytest.mark.parametrize("host", ["127.0.0.1", "0.0.0.0"])
def test_right_key_reaches_the_mcp_server(host):
    headers = {**HEADERS, "Authorization": f"Bearer {TOKEN}"}
    with _client(host) as client:
        response = client.post("/mcp", json=INIT, headers=headers)
        assert response.status_code == 200, response.text
        assert "serverInfo" in response.text
        session = response.headers["mcp-session-id"]
        headers["mcp-session-id"] = session
        client.post("/mcp", json={"jsonrpc": "2.0", "method": "notifications/initialized"}, headers=headers)
        listed = client.post("/mcp", json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, headers=headers)
    assert listed.status_code == 200
    assert '"ping"' in listed.text


def test_key_is_generated_once_and_saved(tmp_path):
    os.environ["BASECAMP_MCP_HOME"] = str(tmp_path)
    os.environ.pop(http_server.TOKEN_ENV, None)
    cli.prepare_environment()
    token, created = http_server.ensure_token(cli.save_settings)
    assert created and len(token) >= http_server.MIN_TOKEN_LENGTH
    assert http_server.TOKEN_ENV in (tmp_path / ".env").read_text()
    assert oct((tmp_path / ".env").stat().st_mode & 0o777) == "0o600"
    again, created_again = http_server.ensure_token(cli.save_settings)
    assert again == token and not created_again


def test_short_key_is_rejected():
    os.environ[http_server.TOKEN_ENV] = "short"
    with pytest.raises(ValueError):
        http_server.ensure_token(lambda values: None)


def test_serve_subcommand_parses():
    args = cli.build_parser().parse_args(["serve", "--host", "0.0.0.0", "--port", "9000"])
    assert (args.command, args.host, args.port) == ("serve", "0.0.0.0", 9000)
    assert cli.build_parser().parse_args(["--full", "serve"]).full is True
