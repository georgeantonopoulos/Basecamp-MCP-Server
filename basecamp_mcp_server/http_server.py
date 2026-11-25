"""Serve the MCP server over HTTP (streamable HTTP transport) instead of stdio.

Two ways to protect it:

- ``oauth`` (default): each user signs in to Basecamp through the MCP client
  (claude.ai custom connectors and other OAuth-capable clients) and every tool
  call uses that user's own Basecamp token. See ``oauth_provider.py``.
- ``key``: one shared access key for a single self-hosting user. Requests must
  carry ``Authorization: Bearer <key>`` and use the token saved by ``login``.
  The key comes from ``BASECAMP_MCP_HTTP_TOKEN`` or is generated once and saved
  to the per-user ``.env``.

The address defaults to this machine only (127.0.0.1).
"""

from __future__ import annotations

import hmac
import json
import os
import secrets
from urllib.parse import urlsplit

TOKEN_ENV = "BASECAMP_MCP_HTTP_TOKEN"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
MCP_PATH = "/mcp"
LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}
MIN_TOKEN_LENGTH = 32


def ensure_token(save_settings) -> tuple[str, bool]:
    """Return (access key, newly created). Creates and saves one when none is set."""
    token = os.environ.get(TOKEN_ENV, "").strip()
    if token:
        if len(token) < MIN_TOKEN_LENGTH:
            raise ValueError(
                f"{TOKEN_ENV} is too short to be safe; use at least {MIN_TOKEN_LENGTH} characters "
                "or remove it so a strong one is generated."
            )
        return token, False
    token = secrets.token_urlsafe(32)
    save_settings({TOKEN_ENV: token})
    return token, True


class BearerTokenMiddleware:
    """Reject any HTTP request whose bearer token doesn't match, in constant time."""

    def __init__(self, app, token: str):
        self.app = app
        self._expected = f"Bearer {token}".encode()

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        supplied = b""
        for name, value in scope.get("headers", []):
            if name == b"authorization":
                supplied = value
                break
        if hmac.compare_digest(supplied, self._expected):
            return await self.app(scope, receive, send)
        body = json.dumps({"error": "unauthorized", "message": "Missing or wrong access key."}).encode()
        await send(
            {
                "type": "http.response.start",
                "status": 401,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"www-authenticate", b'Bearer realm="basecamp-mcp"'),
                    (b"content-length", str(len(body)).encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})


def _host_origin_protection(host: str, public_url: str | None = None) -> bool:
    """Check Host/Origin headers only when the server is reachable on this machine alone.

    The check only allows localhost names, which would refuse every remote client,
    including ones arriving through a proxy or tunnel to a local port. Sign-in (or
    the access key) protects a public server instead.
    """
    public_host = urlsplit(public_url).hostname if public_url else None
    return host in LOOPBACK_HOSTS and not (public_host and public_host not in LOOPBACK_HOSTS)


def build_app(server, token: str, host: str):
    """Access-key mode: wrap a FastMCP server's streamable HTTP app with the key check."""
    app = server.http_app(path=MCP_PATH, host_origin_protection=_host_origin_protection(host))
    return BearerTokenMiddleware(app, token)


def build_oauth_app(server, provider, public_url: str, host: str):
    """Sign-in mode: each user signs in to Basecamp; tools run with their own token."""
    import basecamp_fastmcp
    from basecamp_mcp_server import oauth_provider

    public_url = public_url.rstrip("/")
    server.auth = oauth_provider.FastMCPAuth(provider, public_url)
    basecamp_fastmcp.set_credential_resolver(
        oauth_provider.credential_resolver(provider), oauth_provider.credential_error
    )
    app = server.http_app(
        path=MCP_PATH, host_origin_protection=_host_origin_protection(host, public_url)
    )
    return oauth_provider.BasecampCredentialsMiddleware(app, provider)


def run_app(app, host: str, port: int) -> None:
    import uvicorn

    # The session manager's background tasks start with the Starlette app's lifespan,
    # which uvicorn still drives through the wrapper.
    uvicorn.run(app, host=host, port=port, log_level="warning")
