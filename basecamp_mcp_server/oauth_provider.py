"""Per-user sign-in for remote HTTP mode.

The server is an OAuth 2.1 authorization server for MCP clients (claude.ai
custom connectors, Claude Code, ...) and hands the actual sign-in to Basecamp:

1. The MCP client registers itself (dynamic client registration) and sends the
   user to ``/authorize``.
2. We send the user on to Basecamp's sign-in page (37signals Launchpad).
3. Basecamp redirects back to our callback with a code; we swap it for that
   user's Basecamp token and pick their Basecamp account.
4. We redirect to the MCP client with our own one-time code, which it trades
   at ``/token`` for an MCP access token tied to that user's Basecamp token.

Every tool call then runs with the caller's own Basecamp token; there is no
shared token. MCP tokens are stored only as SHA-256 hashes. The store is a JSON
file in the settings folder, readable only by this user.
"""

from __future__ import annotations

import hashlib
import html
import json
import logging
import os
import secrets
import threading
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urlsplit

from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,

    RefreshToken,
    TokenError,
    construct_redirect_uri,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse, Response

logger = logging.getLogger("basecamp_mcp_oauth")

SCOPE = "basecamp"
ACCESS_TOKEN_SECONDS = 60 * 60
REFRESH_TOKEN_SECONDS = 90 * 24 * 60 * 60
CODE_SECONDS = 5 * 60
PENDING_SECONDS = 15 * 60
BASECAMP_REFRESH_MARGIN = 5 * 60
STORE_NAME = "http_oauth.json"


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class BasecampAuthorizationCode(AuthorizationCode):
    user_key: str
    resource: str | None = None  # declared here too: older mcp releases lack it


class BasecampRefreshToken(RefreshToken):
    user_key: str
    resource: str | None = None  # declared here too: older mcp releases lack it


class BasecampAccessToken(AccessToken):
    user_key: str
    resource: str | None = None  # declared here too: older mcp releases lack it


class _Store:
    """Thread-safe JSON store: registered clients, users, hashed tokens."""

    def __init__(self, path: Path):
        self.path = path
        self.lock = threading.RLock()
        self.data = {"clients": {}, "users": {}, "access": {}, "refresh": {}}
        if path.exists():
            try:
                loaded = json.loads(path.read_text())
                for key in self.data:
                    self.data[key].update(loaded.get(key, {}))
            except (OSError, ValueError) as exc:
                logger.error("Couldn't read %s (%s); starting empty", path, exc)

    def save(self) -> None:
        with self.lock:
            now = time.time()
            for table in ("access", "refresh"):
                expired = [k for k, v in self.data[table].items() if v.get("expires_at") and v["expires_at"] < now]
                for key in expired:
                    del self.data[table][key]
            tmp = self.path.with_suffix(".tmp")
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w") as handle:
                json.dump(self.data, handle)
            os.replace(tmp, self.path)


class BasecampOAuthProvider:
    """OAuthAuthorizationServerProvider that delegates sign-in to Basecamp."""

    def __init__(self, home: Path, callback_url: str, basecamp_oauth=None):
        from basecamp_oauth import BasecampOAuth

        self.callback_url = callback_url
        self.account_path = urlsplit(callback_url).path.rstrip("/") + "/account"
        self.basecamp = basecamp_oauth or BasecampOAuth(redirect_uri=callback_url)
        self.store = _Store(Path(home) / STORE_NAME)
        self.pending: dict[str, dict[str, Any]] = {}
        self.codes: dict[str, BasecampAuthorizationCode] = {}

    # ------------------------------------------------------------------ clients

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        raw = self.store.data["clients"].get(client_id)
        return OAuthClientInformationFull.model_validate(raw) if raw else None

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        with self.store.lock:
            self.store.data["clients"][client_info.client_id] = client_info.model_dump(mode="json")
            self.store.save()

    # ------------------------------------------------------------------ authorize

    async def authorize(self, client: OAuthClientInformationFull, params: AuthorizationParams) -> str:
        self._drop_stale_pending()
        state = secrets.token_urlsafe(32)
        self.pending[state] = {
            "created": time.time(),
            "client_id": client.client_id,
            "params": params,
        }
        return self.basecamp.get_authorization_url(state=state)

    def _drop_stale_pending(self) -> None:
        cutoff = time.time() - PENDING_SECONDS
        for state in [s for s, p in self.pending.items() if p["created"] < cutoff]:
            del self.pending[state]

    async def handle_callback(self, request: Request) -> Response:
        """Basecamp redirects here after the user signs in."""
        import anyio

        self._drop_stale_pending()
        state = request.query_params.get("state", "")
        pending = self.pending.get(state)
        if pending is None:
            return _page("Sign-in link expired", "Start connecting Basecamp again from your app.", 400)
        if request.query_params.get("error") or not request.query_params.get("code"):
            self.pending.pop(state, None)
            reason = request.query_params.get("error") or "Basecamp didn't return a sign-in code."
            return self._client_redirect(pending, error="access_denied", description=reason)
        if "basecamp_token" in pending:
            return _page("Sign-in already used", "Start connecting Basecamp again from your app.", 400)
        code = request.query_params["code"]
        try:
            token = await anyio.to_thread.run_sync(self.basecamp.exchange_code_for_token, code)
            identity = await anyio.to_thread.run_sync(self.basecamp.get_identity, token["access_token"])
        except Exception as exc:
            logger.error("Basecamp code exchange failed: %s", exc)
            self.pending.pop(state, None)
            return _page("Basecamp sign-in failed", "Basecamp didn't accept the sign-in. Try again.", 502)

        import sign_in_messages

        accounts = sign_in_messages.basecamp_accounts(identity)
        if not accounts:
            self.pending.pop(state, None)
            return _page("No Basecamp account", sign_in_messages.no_basecamp_account(identity), 403)
        pending["basecamp_token"] = token
        pending["identity"] = identity
        pending["accounts"] = accounts
        if len(accounts) == 1:
            return self._finish(state, str(accounts[0]["id"]))
        links = "".join(
            f"<li><a href='{html.escape(self.account_path)}?{urlencode({'state': state, 'account': a['id']})}'>"
            f"{html.escape(str(a.get('name')))}</a></li>"
            for a in accounts
        )
        return HTMLResponse(_shell("Choose a Basecamp account", f"<ul>{links}</ul>"))

    async def handle_account_choice(self, request: Request) -> Response:
        state = request.query_params.get("state", "")
        pending = self.pending.get(state)
        if pending is None or "accounts" not in pending:
            return _page("Sign-in link expired", "Start connecting Basecamp again from your app.", 400)
        return self._finish(state, request.query_params.get("account", ""))

    def _finish(self, state: str, account_id: str) -> Response:
        pending = self.pending.get(state)
        account = next((a for a in pending["accounts"] if str(a["id"]) == account_id), None)
        if account is None:
            return _page("Unknown account", "Pick one of the listed Basecamp accounts.", 400)
        self.pending.pop(state, None)
        token = pending["basecamp_token"]
        person = pending["identity"].get("identity", {})
        user_key = f"{person.get('id')}:{account_id}"
        with self.store.lock:
            self.store.data["users"][user_key] = {
                "access_token": token["access_token"],
                "refresh_token": token.get("refresh_token"),
                "expires_at": time.time() + float(token.get("expires_in") or 0) if token.get("expires_in") else None,
                "account_id": account_id,
                "account_name": account.get("name"),
                "person": " ".join(filter(None, [person.get("first_name"), person.get("last_name")])),
            }
            self.store.save()
        params: AuthorizationParams = pending["params"]
        code = secrets.token_urlsafe(32)
        self.codes[code] = BasecampAuthorizationCode(
            code=code,
            scopes=params.scopes or [SCOPE],
            expires_at=time.time() + CODE_SECONDS,
            client_id=pending["client_id"],
            code_challenge=params.code_challenge,
            redirect_uri=params.redirect_uri,
            redirect_uri_provided_explicitly=params.redirect_uri_provided_explicitly,
            resource=params.resource,
            user_key=user_key,
        )
        return self._client_redirect(pending, code=code)

    @staticmethod
    def _client_redirect(pending, code=None, error=None, description=None) -> Response:
        params: AuthorizationParams = pending["params"]
        query = {"code": code} if code else {"error": error, "error_description": description}
        url = construct_redirect_uri(str(params.redirect_uri), state=params.state, **query)
        return RedirectResponse(url, status_code=302, headers={"Cache-Control": "no-store"})

    # ------------------------------------------------------------------ tokens

    async def load_authorization_code(self, client: OAuthClientInformationFull, authorization_code: str):
        code = self.codes.get(authorization_code)
        if code is None or code.client_id != client.client_id:
            return None
        return code

    async def exchange_authorization_code(self, client, authorization_code: BasecampAuthorizationCode) -> OAuthToken:
        if self.codes.pop(authorization_code.code, None) is None:
            raise TokenError("invalid_grant", "authorization code already used")
        return self._issue(client.client_id, authorization_code.scopes, authorization_code.resource, authorization_code.user_key)

    async def load_refresh_token(self, client, refresh_token: str):
        record = self.store.data["refresh"].get(_hash(refresh_token))
        if not record or record["client_id"] != client.client_id:
            return None
        if record.get("expires_at") and record["expires_at"] < time.time():
            return None
        return BasecampRefreshToken(token=refresh_token, **record)

    async def exchange_refresh_token(self, client, refresh_token: BasecampRefreshToken, scopes: list[str]) -> OAuthToken:
        with self.store.lock:
            if self.store.data["refresh"].pop(_hash(refresh_token.token), None) is None:
                raise TokenError("invalid_grant", "refresh token already used")
        return self._issue(client.client_id, scopes or refresh_token.scopes, refresh_token.resource, refresh_token.user_key)

    def _issue(self, client_id: str, scopes: list[str], resource: str | None, user_key: str) -> OAuthToken:
        access, refresh = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        now = int(time.time())
        common = {"client_id": client_id, "scopes": scopes, "resource": resource, "user_key": user_key}
        with self.store.lock:
            self.store.data["access"][_hash(access)] = {**common, "expires_at": now + ACCESS_TOKEN_SECONDS}
            self.store.data["refresh"][_hash(refresh)] = {**common, "expires_at": now + REFRESH_TOKEN_SECONDS}
            self.store.save()
        return OAuthToken(
            access_token=access,
            token_type="Bearer",
            expires_in=ACCESS_TOKEN_SECONDS,
            refresh_token=refresh,
            scope=" ".join(scopes),
        )

    async def load_access_token(self, token: str) -> BasecampAccessToken | None:
        record = self.store.data["access"].get(_hash(token))
        if not record or record["expires_at"] < time.time():
            return None
        if record["user_key"] not in self.store.data["users"]:
            return None
        return BasecampAccessToken(token=token, **record)

    async def revoke_token(self, token) -> None:
        with self.store.lock:
            for table in ("access", "refresh"):
                self.store.data[table].pop(_hash(token.token), None)
            self.store.save()

    # ------------------------------------------------------------------ per-request Basecamp credentials

    def credentials_for(self, user_key: str) -> dict | None:
        """The user's Basecamp token and account, refreshed with Basecamp when near expiry."""
        with self.store.lock:
            user = self.store.data["users"].get(user_key)
            if not user:
                return None
            expires_at = user.get("expires_at")
            if expires_at and expires_at - BASECAMP_REFRESH_MARGIN < time.time():
                if not user.get("refresh_token"):
                    return None
                try:
                    fresh = self.basecamp.refresh_token(user["refresh_token"])
                except Exception as exc:
                    logger.error("Basecamp token refresh failed for one user: %s", exc)
                    return None
                user["access_token"] = fresh["access_token"]
                user["refresh_token"] = fresh.get("refresh_token") or user["refresh_token"]
                user["expires_at"] = time.time() + float(fresh["expires_in"]) if fresh.get("expires_in") else None
                self.store.save()
            return {"access_token": user["access_token"], "account_id": user["account_id"]}


def current_access_token() -> AccessToken | None:
    """The MCP access token of the request being handled, if any."""
    from mcp.server.lowlevel.server import request_ctx

    try:
        request = request_ctx.get().request
    except LookupError:
        request = None
    user = getattr(request, "scope", {}).get("user") if request is not None else None
    token = getattr(user, "access_token", None)
    if token is not None:
        return token
    from mcp.server.auth.middleware.auth_context import get_access_token

    return get_access_token()


def credential_resolver(provider: BasecampOAuthProvider):
    def resolve() -> dict | None:
        token = current_access_token()
        user_key = getattr(token, "user_key", None)
        if not user_key:
            return None
        return provider.credentials_for(user_key)

    return resolve


def credential_error() -> tuple[str, str]:
    return (
        "Basecamp sign-in required",
        "Your Basecamp sign-in for this connector has expired or was removed. "
        "Disconnect and reconnect the Basecamp connector to sign in again.",
    )


def _shell(title: str, body_html: str) -> str:
    return (
        "<!doctype html><meta charset='utf-8'><title>Basecamp MCP</title>"
        "<body style='font-family:system-ui;max-width:32rem;margin:4rem auto'>"
        f"<h2>{html.escape(title)}</h2>{body_html}</body>"
    )


def _page(title: str, message: str, status: int) -> HTMLResponse:
    return HTMLResponse(_shell(title, f"<p>{html.escape(message)}</p>"), status_code=status)
