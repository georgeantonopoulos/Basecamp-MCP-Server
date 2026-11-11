"""Serve the MCP server over HTTP (streamable HTTP transport) instead of stdio.

Whoever reaches this address acts in Basecamp as the signed-in user, so every
request must carry ``Authorization: Bearer <access key>``. The key comes from
``BASECAMP_MCP_HTTP_TOKEN`` or is generated once and saved to the per-user
``.env``. The address defaults to this machine only (127.0.0.1).
"""

from __future__ import annotations

import hmac
import json
import os
import secrets

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


def build_app(server, token: str, host: str):
    """Wrap a FastMCP server's streamable HTTP app with the access-key check."""
    server.settings.streamable_http_path = MCP_PATH
    if host not in LOOPBACK_HOSTS:
        # The library's built-in Host/Origin check only allows localhost names, which
        # would refuse every remote client. The access key is the protection here.
        from mcp.server.transport_security import TransportSecuritySettings

        server.settings.transport_security = TransportSecuritySettings(enable_dns_rebinding_protection=False)
    return BearerTokenMiddleware(server.streamable_http_app(), token)


def serve(server, token: str, host: str, port: int) -> None:
    import uvicorn

    app = build_app(server, token, host)
    # The session manager's background tasks start with the Starlette app's lifespan,
    # which uvicorn still drives through the wrapper.
    uvicorn.run(app, host=host, port=port, log_level="warning")
