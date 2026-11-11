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


def _prepare(server, host: str) -> None:
    server.settings.streamable_http_path = MCP_PATH
    if host not in LOOPBACK_HOSTS:
        # The library's built-in Host/Origin check only allows localhost names, which
        # would refuse every remote client. Sign-in (or the access key) protects it instead.
        from mcp.server.transport_security import TransportSecuritySettings

        server.settings.transport_security = TransportSecuritySettings(enable_dns_rebinding_protection=False)


def build_app(server, token: str, host: str):
    """Access-key mode: wrap a FastMCP server's streamable HTTP app with the key check."""
    _prepare(server, host)
    return BearerTokenMiddleware(server.streamable_http_app(), token)


def build_oauth_app(server, provider, public_url: str, host: str):
    """Sign-in mode: each user signs in to Basecamp; tools run with their own token."""
    from mcp.server.auth.provider import ProviderTokenVerifier
    from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions, RevocationOptions
    from starlette.routing import Route

    import basecamp_fastmcp
    from basecamp_mcp_server import oauth_provider

    _prepare(server, host)
    public_url = public_url.rstrip("/")
    extra = {}
    if "validate_token_resource" in AuthSettings.model_fields:
        # Tokens are only ever issued by this server for this server, and some clients
        # don't send a resource indicator, so don't require one.
        extra["validate_token_resource"] = False
    server.settings.auth = AuthSettings(
        **extra,
        issuer_url=public_url,
        resource_server_url=public_url + MCP_PATH,
        client_registration_options=ClientRegistrationOptions(
            enabled=True, valid_scopes=[oauth_provider.SCOPE], default_scopes=[oauth_provider.SCOPE]
        ),
        revocation_options=RevocationOptions(enabled=True),
        required_scopes=[oauth_provider.SCOPE],
    )
    server._auth_server_provider = provider
    server._token_verifier = ProviderTokenVerifier(provider)
    callback_path = urlsplit(provider.callback_url).path or "/"
    server._custom_starlette_routes.extend(
        [
            Route(callback_path, provider.handle_callback, methods=["GET"]),
            Route(provider.account_path, provider.handle_account_choice, methods=["GET"]),
        ]
    )
    basecamp_fastmcp.set_credential_resolver(
        oauth_provider.credential_resolver(provider), oauth_provider.credential_error
    )
    return server.streamable_http_app()


def run_app(app, host: str, port: int) -> None:
    import uvicorn

    # The session manager's background tasks start with the Starlette app's lifespan,
    # which uvicorn still drives through the wrapper.
    uvicorn.run(app, host=host, port=port, log_level="warning")
