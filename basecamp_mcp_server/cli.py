"""Command-line entry point for the installed Basecamp MCP server.

    basecamp-mcp-server            run the MCP server over stdio (what MCP clients launch)
    basecamp-mcp-server login      sign in to Basecamp in the browser and save the token
    basecamp-mcp-server status     show where settings live and check the saved sign-in
    basecamp-mcp-server config X   print the snippet to add the server to an MCP client

Settings live in one folder per user (override with BASECAMP_MCP_HOME):
``.env`` for the OAuth app credentials and ``oauth_tokens.json`` for the token.
"""

from __future__ import annotations

import argparse
import getpass
import html
import json
import os
import secrets
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from basecamp_mcp_server import __version__

PACKAGE = "basecamp-mcp-server"
LOGIN_COMMAND = f"uvx {PACKAGE} login"
DEFAULT_REDIRECT_URI = "http://localhost:8000/auth/callback"
DEFAULT_USER_AGENT = f"Basecamp MCP Server ({PACKAGE}; +https://github.com/georgeantonopoulos/Basecamp-MCP-Server)"
INTEGRATIONS_URL = "https://launchpad.37signals.com/integrations"
LOGIN_TIMEOUT_SECONDS = 300


class LoginError(Exception):
    """A sign-in problem the user can fix; printed without a traceback."""


# --------------------------------------------------------------------------- settings

def home_dir() -> Path:
    """Per-user settings folder."""
    override = os.environ.get("BASECAMP_MCP_HOME")
    if override:
        return Path(os.path.expanduser(os.path.expandvars(override)))
    if os.name == "nt":
        base = os.environ.get("APPDATA") or os.path.expanduser("~\\AppData\\Roaming")
        return Path(base) / PACKAGE
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return Path(base) / PACKAGE


def env_file() -> Path:
    return home_dir() / ".env"


def prepare_environment() -> Path:
    """Point every server module at the per-user folder. Must run before importing them."""
    home = home_dir()
    home.mkdir(parents=True, exist_ok=True)
    try:
        home.chmod(0o700)
    except OSError:
        pass
    from dotenv import load_dotenv

    load_dotenv(env_file())  # real environment variables still win
    os.environ.setdefault("BASECAMP_MCP_HOME", str(home))
    os.environ.setdefault("BASECAMP_MCP_TOKEN_FILE", str(home / "oauth_tokens.json"))
    os.environ.setdefault("BASECAMP_REDIRECT_URI", DEFAULT_REDIRECT_URI)
    os.environ.setdefault("USER_AGENT", DEFAULT_USER_AGENT)
    os.environ.setdefault("BASECAMP_MCP_LOGIN_COMMAND", LOGIN_COMMAND)
    return home


def save_settings(values: dict) -> None:
    """Merge KEY=value pairs into the per-user .env, readable only by this user."""
    path = env_file()
    lines = path.read_text().splitlines() if path.exists() else []
    remaining = dict(values)
    out = []
    for line in lines:
        key = line.split("=", 1)[0].strip()
        if key in remaining:
            out.append(f"{key}={json.dumps(remaining.pop(key))}")
        else:
            out.append(line)
    out.extend(f"{key}={json.dumps(value)}" for key, value in remaining.items())
    path.write_text("\n".join(out) + "\n")
    try:
        path.chmod(0o600)
    except OSError:
        pass
    os.environ.update(values)


# --------------------------------------------------------------------------- login

def _ensure_credentials(interactive: bool) -> None:
    if os.environ.get("BASECAMP_CLIENT_ID") and os.environ.get("BASECAMP_CLIENT_SECRET"):
        return
    if not interactive:
        raise LoginError(
            "BASECAMP_CLIENT_ID and BASECAMP_CLIENT_SECRET are not set. "
            f"Run `{LOGIN_COMMAND}` in a terminal to enter them."
        )
    redirect = os.environ["BASECAMP_REDIRECT_URI"]
    print(
        "First, register this server as a Basecamp app (one time, free):\n"
        f"  1. Open {INTEGRATIONS_URL} and choose 'Register another application'.\n"
        "  2. Any name and website will do.\n"
        f"  3. Set the Redirect URI to exactly: {redirect}\n"
        "  4. Copy the Client ID and Client Secret it shows you.\n"
    )
    client_id = input("Client ID: ").strip()
    client_secret = getpass.getpass("Client Secret (hidden): ").strip()
    if not client_id or not client_secret:
        raise LoginError("Both the Client ID and the Client Secret are needed.")
    save_settings({"BASECAMP_CLIENT_ID": client_id, "BASECAMP_CLIENT_SECRET": client_secret})
    print(f"Saved to {env_file()}\n")


def _page(title: str, body: str) -> bytes:
    return (
        "<!doctype html><meta charset='utf-8'><title>Basecamp MCP</title>"
        "<body style='font-family:system-ui;max-width:32rem;margin:4rem auto'>"
        f"<h2>{html.escape(title)}</h2><p>{html.escape(body)}</p></body>"
    ).encode()


def wait_for_callback(redirect_uri: str, state: str, timeout: float, on_ready=None) -> str:
    """Serve the redirect URI once and return the authorization code."""
    parts = urlsplit(redirect_uri)
    if parts.scheme != "http" or parts.hostname not in ("localhost", "127.0.0.1"):
        raise LoginError(
            f"The redirect URI must be a local http address for sign-in, got {redirect_uri}"
        )
    result: dict = {}
    done = threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 (http.server API)
            url = urlsplit(self.path)
            if url.path != (parts.path or "/"):
                self.send_response(404)
                self.end_headers()
                return
            query = parse_qs(url.query)
            if done.is_set() or query.get("state", [None])[0] != state:
                # Not the response we're waiting for (a stray or repeated request):
                # answer it, but keep waiting for the real one.
                self._reply(400, _page("Sign-in link expired", "Run the login command again."))
                return
            if "error" in query:
                result["error"] = f"Basecamp refused the sign-in: {query['error'][0]}"
            elif not query.get("code"):
                result["error"] = "Basecamp didn't return an authorization code."
            else:
                result["code"] = query["code"][0]
            ok = "code" in result
            self._reply(
                200 if ok else 400,
                _page("Signed in to Basecamp", "You can close this tab and go back to the terminal.")
                if ok
                else _page("Sign-in failed", result["error"]),
            )
            done.set()

        def _reply(self, status_code, body):
            self.send_response(status_code)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):  # keep the terminal quiet
            pass

    try:
        server = HTTPServer((parts.hostname, parts.port or 80), Handler)
    except OSError as exc:
        raise LoginError(
            f"Couldn't listen on {parts.hostname}:{parts.port}: {exc}. "
            "Close whatever is using that port (an old oauth_app.py?) and try again."
        ) from exc
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        if on_ready:
            on_ready()
        if not done.wait(timeout):
            raise LoginError("Timed out waiting for the browser sign-in. Run login again when ready.")
    finally:
        server.shutdown()
        server.server_close()
    if "error" in result:
        raise LoginError(result["error"])
    return result["code"]


def choose_account(identity: dict, wanted: str | None, interactive: bool) -> dict:
    """Pick the Basecamp (3 or 4) account to use; fail clearly when there isn't one."""
    accounts = [a for a in identity.get("accounts", []) if a.get("product") == "bc3"]
    if wanted:
        for account in accounts:
            if str(account.get("id")) == str(wanted):
                return account
        raise LoginError(f"Account {wanted} isn't among this login's Basecamp accounts.")
    if not accounts:
        products = sorted({a.get("product", "?") for a in identity.get("accounts", [])})
        found = f" (found only: {', '.join(products)})" if products else ""
        raise LoginError(
            "This Basecamp login has no Basecamp 3 or 4 account" + found + ". "
            "Sign in with a user who belongs to one."
        )
    if len(accounts) == 1:
        return accounts[0]
    listing = "\n".join(f"  {i}. {a.get('name')} (id {a.get('id')})" for i, a in enumerate(accounts, 1))
    if not interactive:
        raise LoginError(f"Several Basecamp accounts found; rerun with --account-id:\n{listing}")
    print(f"This login can use several Basecamp accounts:\n{listing}")
    while True:
        choice = input(f"Which one? [1-{len(accounts)}]: ").strip()
        if choice.isdigit() and 1 <= int(choice) <= len(accounts):
            return accounts[int(choice) - 1]


def login(args) -> int:
    prepare_environment()
    interactive = sys.stdin.isatty()
    _ensure_credentials(interactive)

    from basecamp_oauth import BasecampOAuth
    import token_storage

    oauth = BasecampOAuth()
    state = secrets.token_urlsafe(24)
    auth_url = oauth.get_authorization_url(state=state)

    def open_browser():
        print(
            "Opening Basecamp in your browser to sign in. If it doesn't open, visit:\n  " + auth_url,
            flush=True,
        )
        if not args.no_browser:
            webbrowser.open(auth_url)

    code = wait_for_callback(oauth.redirect_uri, state, args.timeout, on_ready=open_browser)
    try:
        token = oauth.exchange_code_for_token(code)
        identity = oauth.get_identity(token["access_token"])
    except Exception as exc:
        raise LoginError(f"Basecamp sign-in didn't complete: {exc}") from exc
    account = choose_account(identity, args.account_id, interactive)
    if not token_storage.store_token(
        access_token=token["access_token"],
        refresh_token=token.get("refresh_token"),
        expires_in=token.get("expires_in"),
        account_id=str(account["id"]),
    ):
        raise LoginError(f"Couldn't save the token to {token_storage.TOKEN_FILE}")
    person = identity.get("identity", {})
    who = " ".join(filter(None, [person.get("first_name"), person.get("last_name")])) or "you"
    print(f"\nSigned in as {who} to '{account.get('name')}' (account {account['id']}).")
    print(f"Token saved to {token_storage.TOKEN_FILE}")
    print(f"\nNext: add the server to your MCP client. For example, run `uvx {PACKAGE} config claude-desktop`.")
    return 0


# --------------------------------------------------------------------------- status / config / run

def status(args) -> int:
    home = prepare_environment()
    import token_storage

    print(f"Settings folder: {home}")
    has_app = bool(os.environ.get("BASECAMP_CLIENT_ID") and os.environ.get("BASECAMP_CLIENT_SECRET"))
    print(f"Basecamp app credentials: {'set' if has_app else 'missing'}")
    token = token_storage.get_token()
    if not token or not token.get("access_token"):
        print(f"Signed in: no. Run `{LOGIN_COMMAND}`.")
        return 1
    print(f"Signed in: yes (account {token.get('account_id')}, token expires {token.get('expires_at')})")
    if args.offline:
        return 0
    import auth_manager
    from basecamp_client import BasecampClient

    if not auth_manager.ensure_authenticated():
        print(f"The saved token no longer works and couldn't be refreshed. Run `{LOGIN_COMMAND}`.")
        return 1
    token = token_storage.get_token()
    client = BasecampClient(
        access_token=token["access_token"],
        account_id=token.get("account_id") or os.environ.get("BASECAMP_ACCOUNT_ID"),
        user_agent=os.environ["USER_AGENT"],
        auth_mode="oauth",
    )
    response = client.get("my/profile.json")
    if response.status_code != 200:
        print(f"Basecamp answered {response.status_code}. Run `{LOGIN_COMMAND}` to sign in again.")
        return 1
    print(f"Connection check: OK, Basecamp knows you as {response.json().get('name')}.")
    return 0


def uvx_command() -> str:
    """Full path to uvx when known: desktop apps often don't see the shell's PATH."""
    import shutil

    return shutil.which("uvx") or "uvx"


def client_config(client: str, full: bool) -> str:
    args = [PACKAGE] + (["--full"] if full else [])
    if client == "claude-code":
        return "claude mcp add basecamp -- uvx " + " ".join(args)
    command = uvx_command()
    if client == "codex":
        quoted = ", ".join(json.dumps(a) for a in args)
        return f"[mcp_servers.basecamp]\ncommand = {json.dumps(command)}\nargs = [{quoted}]"
    entry = {"command": command, "args": args}
    return json.dumps({"mcpServers": {"basecamp": entry}}, indent=2)


CONFIG_HELP = {
    "claude-desktop": "Add this to claude_desktop_config.json (Settings > Developer > Edit Config), then restart Claude Desktop:",
    "cursor": "Add this to ~/.cursor/mcp.json (or .cursor/mcp.json in a project), then restart Cursor:",
    "claude-code": "Run this command:",
    "codex": "Add this to ~/.codex/config.toml:",
    "generic": "Most MCP clients accept this JSON:",
}


def config(args) -> int:
    print(CONFIG_HELP[args.client])
    print()
    print(client_config(args.client, args.full))
    return 0


def run(args) -> int:
    prepare_environment()
    if args.full:
        from basecamp_fastmcp import mcp

        mcp.run(transport="stdio")
    else:
        from basecamp_retrieval_mcp import retrieval_mcp

        retrieval_mcp.run(transport="stdio")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=PACKAGE, description="Basecamp MCP server")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument(
        "--full",
        action="store_true",
        help="advertise all 210 tools directly instead of the 4 discovery tools",
    )
    sub = parser.add_subparsers(dest="command")
    run_p = sub.add_parser("run", help="run the MCP server over stdio (the default)")
    # SUPPRESS keeps a --full given before the subcommand from being reset.
    run_p.add_argument("--full", action="store_true", default=argparse.SUPPRESS, help=argparse.SUPPRESS)

    login_p = sub.add_parser("login", help="sign in to Basecamp in the browser")
    login_p.add_argument("--account-id", help="Basecamp account to use when you belong to several")
    login_p.add_argument("--no-browser", action="store_true", help="print the sign-in link instead of opening it")
    login_p.add_argument("--timeout", type=float, default=LOGIN_TIMEOUT_SECONDS, help=argparse.SUPPRESS)

    status_p = sub.add_parser("status", help="show settings and check the saved sign-in")
    status_p.add_argument("--offline", action="store_true", help="don't contact Basecamp")

    config_p = sub.add_parser("config", help="print the setup snippet for an MCP client")
    config_p.add_argument("client", choices=sorted(CONFIG_HELP))
    config_p.add_argument(
        "--full", action="store_true", default=argparse.SUPPRESS, help="configure all 210 tools directly"
    )
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    handlers = {None: run, "run": run, "login": login, "status": status, "config": config}
    try:
        return handlers[args.command](args)
    except LoginError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nCancelled.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
