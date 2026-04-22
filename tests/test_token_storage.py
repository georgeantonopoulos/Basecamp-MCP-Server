import importlib
from pathlib import Path

import pytest

import token_storage


@pytest.mark.parametrize(
    "configured_path",
    [
        "~/tokens/oauth_tokens.json",
        "$HOME/tokens/oauth_tokens.json",
    ],
)
def test_store_token_expands_configured_token_path(configured_path, tmp_path, monkeypatch):
    home_dir = tmp_path / "home"
    working_dir = tmp_path / "workspace"
    home_dir.mkdir()
    working_dir.mkdir()

    monkeypatch.chdir(working_dir)
    monkeypatch.setenv("HOME", str(home_dir))
    monkeypatch.setenv("BASECAMP_MCP_TOKEN_FILE", configured_path)

    reloaded_token_storage = importlib.reload(token_storage)

    try:
        expected_token_file = home_dir / "tokens" / "oauth_tokens.json"

        assert Path(reloaded_token_storage.TOKEN_FILE) == expected_token_file

        stored = reloaded_token_storage.store_token(
            "access-token",
            refresh_token="refresh-token",
            account_id="12345",
        )

        assert stored is True
        assert expected_token_file.exists()
        assert not (working_dir / "~").exists()
    finally:
        monkeypatch.delenv("BASECAMP_MCP_TOKEN_FILE", raising=False)
        importlib.reload(token_storage)
