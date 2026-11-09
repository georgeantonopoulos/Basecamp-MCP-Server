"""Guards for the installable package and its command-line tool."""

import ast
import json
import os
import re
import stat
import threading
import time
import urllib.request
from pathlib import Path

import pytest

from basecamp_mcp_server import cli

ROOT = Path(__file__).resolve().parent.parent
ENTRY_MODULES = {"basecamp_retrieval_mcp", "basecamp_fastmcp"}


def _listed_modules(section):
    """Root-level .py files named in one [tool.hatch...] table of pyproject.toml."""
    text = (ROOT / "pyproject.toml").read_text()
    start = text.index(section)
    end = text.find("\n[", start + 1)
    block = text[start:end if end != -1 else None]
    return set(re.findall(r'"([a-z_]+)\.py"', block))


def _local_imports(module):
    tree = ast.parse((ROOT / f"{module}.py").read_text())
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module.split(".")[0])
    return {name for name in names if (ROOT / f"{name}.py").exists()}


def _needed_modules():
    needed, todo = set(), list(ENTRY_MODULES)
    while todo:
        module = todo.pop()
        if module not in needed:
            needed.add(module)
            todo.extend(_local_imports(module))
    return needed


@pytest.mark.parametrize(
    "section",
    [
        "[tool.hatch.build.targets.wheel]",
        "[tool.hatch.build.targets.wheel.force-include]",
        "[tool.hatch.build.targets.sdist]",
    ],
)
def test_package_ships_every_module_the_servers_import(section):
    missing = _needed_modules() - _listed_modules(section)
    assert not missing, f"add to {section} in pyproject.toml: {sorted(missing)}"


def test_cli_only_imports_shipped_modules():
    tree = ast.parse((ROOT / "basecamp_mcp_server" / "cli.py").read_text())
    imported = {
        node.module.split(".")[0] if isinstance(node, ast.ImportFrom) else alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom)) and getattr(node, "level", 0) == 0
        for alias in (node.names if isinstance(node, ast.Import) else [None])
        if isinstance(node, ast.ImportFrom) or alias
    }
    local = {name for name in imported if (ROOT / f"{name}.py").exists()}
    assert local <= _listed_modules("[tool.hatch.build.targets.wheel]")


def test_home_dir_honours_override(tmp_path, monkeypatch):
    monkeypatch.setenv("BASECAMP_MCP_HOME", str(tmp_path / "bc"))
    assert cli.home_dir() == tmp_path / "bc"


def test_prepare_environment_points_servers_at_user_folder(tmp_path, monkeypatch):
    monkeypatch.setenv("BASECAMP_MCP_HOME", str(tmp_path))
    for key in ("BASECAMP_MCP_TOKEN_FILE", "USER_AGENT", "BASECAMP_REDIRECT_URI", "BASECAMP_MCP_LOGIN_COMMAND"):
        monkeypatch.delenv(key, raising=False)
    (tmp_path / ".env").write_text('BASECAMP_CLIENT_ID="abc"\n')
    monkeypatch.delenv("BASECAMP_CLIENT_ID", raising=False)

    cli.prepare_environment()

    assert os.environ["BASECAMP_MCP_TOKEN_FILE"] == str(tmp_path / "oauth_tokens.json")
    assert os.environ["BASECAMP_CLIENT_ID"] == "abc"
    assert os.environ["BASECAMP_REDIRECT_URI"] == cli.DEFAULT_REDIRECT_URI
    assert os.environ["BASECAMP_MCP_LOGIN_COMMAND"] == cli.LOGIN_COMMAND
    assert "@" not in os.environ["USER_AGENT"]  # no personal contact details shipped


def test_save_settings_merges_and_is_private(tmp_path, monkeypatch):
    monkeypatch.setenv("BASECAMP_MCP_HOME", str(tmp_path))
    (tmp_path / ".env").write_text('KEEP="1"\nBASECAMP_CLIENT_ID="old"\n')
    monkeypatch.delenv("BASECAMP_CLIENT_ID", raising=False)

    cli.save_settings({"BASECAMP_CLIENT_ID": "new", "BASECAMP_CLIENT_SECRET": "s"})

    text = (tmp_path / ".env").read_text()
    assert 'KEEP="1"' in text and 'BASECAMP_CLIENT_ID="new"' in text and "old" not in text
    if os.name != "nt":
        assert stat.S_IMODE((tmp_path / ".env").stat().st_mode) == 0o600


def test_choose_account_fails_clearly_without_a_basecamp_account():
    identity = {"accounts": [{"id": 1, "product": "campfire", "name": "Chat"}]}
    with pytest.raises(cli.LoginError, match="no Basecamp 3 or 4 account.*campfire"):
        cli.choose_account(identity, None, interactive=False)


def test_choose_account_picks_single_or_requested_account():
    one = {"accounts": [{"id": 7, "product": "bc3", "name": "Team"}]}
    assert cli.choose_account(one, None, interactive=False)["id"] == 7
    two = {"accounts": [{"id": 7, "product": "bc3"}, {"id": 8, "product": "bc3"}]}
    assert cli.choose_account(two, "8", interactive=False)["id"] == 8
    with pytest.raises(cli.LoginError, match="--account-id"):
        cli.choose_account(two, None, interactive=False)
    with pytest.raises(cli.LoginError, match="isn't among"):
        cli.choose_account(two, "9", interactive=False)


def _free_port():
    import socket

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _hit_later(url):
    def go():
        time.sleep(0.2)
        try:
            urllib.request.urlopen(url, timeout=5).read()
        except Exception:
            pass

    threading.Thread(target=go, daemon=True).start()


def test_callback_returns_code_when_state_matches():
    port = _free_port()
    redirect = f"http://127.0.0.1:{port}/auth/callback"
    code = cli.wait_for_callback(
        redirect, "s1", timeout=5, on_ready=lambda: _hit_later(redirect + "?code=abc&state=s1")
    )
    assert code == "abc"


def test_callback_ignores_stray_requests_and_waits_for_the_real_one():
    port = _free_port()
    redirect = f"http://127.0.0.1:{port}/auth/callback"

    def stray_then_real():
        _hit_later(redirect + "?code=evil&state=wrong")
        _hit_later(redirect)  # no state at all
        threading.Timer(0.6, lambda: _hit_later(redirect + "?code=abc&state=s1")).start()

    assert cli.wait_for_callback(redirect, "s1", timeout=5, on_ready=stray_then_real) == "abc"


def test_callback_times_out_when_only_stray_requests_arrive():
    port = _free_port()
    redirect = f"http://127.0.0.1:{port}/auth/callback"
    with pytest.raises(cli.LoginError, match="Timed out"):
        cli.wait_for_callback(
            redirect, "s1", timeout=1.5, on_ready=lambda: _hit_later(redirect + "?code=abc&state=evil")
        )


def test_login_prompts_fail_clearly_when_input_is_empty(monkeypatch):
    """Windows treats an empty input as a terminal; login must not crash with EOFError."""
    for key in ("BASECAMP_CLIENT_ID", "BASECAMP_CLIENT_SECRET"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("BASECAMP_REDIRECT_URI", cli.DEFAULT_REDIRECT_URI)

    def eof(*_):
        raise EOFError

    monkeypatch.setattr("builtins.input", eof)
    with pytest.raises(cli.LoginError, match="BASECAMP_CLIENT_ID"):
        cli._ensure_credentials(interactive=True)

    two = {"accounts": [{"id": 7, "product": "bc3"}, {"id": 8, "product": "bc3"}]}
    with pytest.raises(cli.LoginError, match="--account-id"):
        cli.choose_account(two, None, interactive=True)


def test_full_flag_works_before_or_after_the_subcommand():
    parser = cli.build_parser()
    assert parser.parse_args(["--full", "config", "cursor"]).full is True
    assert parser.parse_args(["config", "cursor", "--full"]).full is True
    assert parser.parse_args(["config", "cursor"]).full is False
    assert parser.parse_args(["--full"]).full is True
    assert parser.parse_args(["run", "--full"]).full is True


def test_callback_requires_local_http_redirect():
    with pytest.raises(cli.LoginError, match="local http"):
        cli.wait_for_callback("https://example.com/cb", "s", timeout=1)


def test_client_config_snippets(monkeypatch):
    monkeypatch.setattr(cli, "uvx_command", lambda: "/opt/bin/uvx")
    desktop = json.loads(cli.client_config("claude-desktop", full=False))
    assert desktop == {"mcpServers": {"basecamp": {"command": "/opt/bin/uvx", "args": ["basecamp-mcp-server"]}}}
    assert cli.client_config("claude-code", full=True) == "claude mcp add basecamp -- uvx basecamp-mcp-server --full"
    codex = cli.client_config("codex", full=False)
    assert 'command = "/opt/bin/uvx"' in codex and 'args = ["basecamp-mcp-server"]' in codex


def test_uvx_command_falls_back_to_bare_name(monkeypatch):
    import shutil

    monkeypatch.setattr(shutil, "which", lambda name: None)
    assert cli.uvx_command() == "uvx"


def test_sign_in_messages_follow_login_command(monkeypatch):
    import sign_in_messages

    monkeypatch.delenv("BASECAMP_MCP_LOGIN_COMMAND", raising=False)
    assert "localhost:8000" in sign_in_messages.expired()
    monkeypatch.setenv("BASECAMP_MCP_LOGIN_COMMAND", "uvx basecamp-mcp-server login")
    for message in (
        sign_in_messages.expired(),
        sign_in_messages.expired_during_call(),
        sign_in_messages.sign_in_required(),
    ):
        assert "uvx basecamp-mcp-server login" in message and "localhost" not in message


def test_version_matches_changelog_or_is_new():
    from basecamp_mcp_server import __version__

    assert re.fullmatch(r"\d+\.\d+\.\d+", __version__)
