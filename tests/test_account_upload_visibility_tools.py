"""Tests for account, client visibility, and upload lifecycle surfaces."""

import asyncio
from unittest.mock import MagicMock, Mock, patch

import basecamp_fastmcp
from basecamp_client import BasecampClient
from mcp_server_cli import MCPServer


def test_account_client_uses_documented_routes():
    client = BasecampClient.__new__(BasecampClient)
    account = MagicMock(status_code=200)
    account.json.return_value = {"id": "account-1", "name": "Studio"}
    renamed = MagicMock(status_code=200)
    renamed.json.return_value = {"id": "account-1", "name": "New Studio"}
    removed = MagicMock(status_code=204)

    with patch.object(client, "get", return_value=account) as get:
        assert client.get_account()["name"] == "Studio"
    with patch.object(client, "put", return_value=renamed) as put:
        assert client.update_account_name("New Studio")["name"] == "New Studio"
    with patch.object(client, "delete", return_value=removed) as delete:
        assert client.remove_account_logo() is True

    get.assert_called_once_with("account.json")
    put.assert_called_once_with("account/name.json", {"name": "New Studio"})
    delete.assert_called_once_with("account/logo.json")


def test_account_logo_upload_validates_file_and_uses_multipart(tmp_path):
    client = BasecampClient.__new__(BasecampClient)
    client.base_url = "https://3.basecampapi.com/account-1"
    client.auth = None
    client.headers = {"User-Agent": "Test App", "Content-Type": "application/json"}
    logo = tmp_path / "logo.png"
    logo.write_bytes(b"png")
    response = MagicMock(status_code=204)

    with patch("basecamp_client.requests.put", return_value=response) as put:
        assert client.update_account_logo(str(logo)) is True

    assert put.call_args.args[0].endswith("/account/logo.json")
    assert "Content-Type" not in put.call_args.kwargs["headers"]
    assert put.call_args.kwargs["files"]["logo"][0] == "logo.png"

    bad = tmp_path / "logo.txt"
    bad.write_text("not an image")
    try:
        client.update_account_logo(str(bad))
    except ValueError as exc:
        assert "logo must be" in str(exc)
    else:
        raise AssertionError("invalid account logo format was accepted")


def test_visibility_and_upload_client_use_flat_routes():
    client = BasecampClient.__new__(BasecampClient)
    updated = MagicMock(status_code=200)
    updated.json.return_value = {"id": "recording-1"}
    versions = MagicMock(status_code=200, links={})
    versions.json.return_value = [
        {"action": "created"}, {"action": "blob_changed"}
    ]
    created = MagicMock(status_code=201)
    created.json.return_value = {"id": "upload-1"}

    with patch.object(client, "put", return_value=updated) as put:
        assert client.update_recording_visibility("recording-1", True)["id"] == "recording-1"
        assert client.update_upload("upload-1", description="Updated")["id"] == "recording-1"
    with patch.object(client, "_get_paginated_collection", return_value=versions.json.return_value) as collect:
        assert client.get_upload_versions("upload-1", "blob_changed") == [{"action": "blob_changed"}]
    with patch.object(client, "post", return_value=created) as post:
        assert client.create_upload_version("upload-1", "sgid-1", base_name="new")['id'] == "upload-1"

    assert put.call_args_list[0].args == (
        "recordings/recording-1/client_visibility.json", {"visible_to_clients": True}
    )
    assert put.call_args_list[1].args == ("uploads/upload-1.json", {"description": "Updated"})
    collect.assert_called_once_with("uploads/upload-1/versions.json")
    post.assert_called_once_with(
        "uploads/upload-1/versions.json",
        {"attachable_sgid": "sgid-1", "base_name": "new"},
    )


def test_upload_and_visibility_tools_are_registered_and_structured():
    expected = {
        "get_account", "update_account_name", "update_account_logo", "remove_account_logo",
        "update_recording_visibility", "update_upload", "get_upload_versions",
        "create_upload_version",
    }
    fastmcp_names = set(basecamp_fastmcp.mcp._tool_manager._tools)
    cli_names = {tool["name"] for tool in MCPServer().tools}
    assert expected <= fastmcp_names
    assert fastmcp_names == cli_names

    client = Mock()
    client.get_account.return_value = {"id": "account-1"}
    client.update_recording_visibility.return_value = {"id": "recording-1"}
    client.get_upload_versions.return_value = [{"action": "created"}]

    async def run():
        with patch.object(basecamp_fastmcp, "_get_basecamp_client", return_value=client):
            return (
                await basecamp_fastmcp.get_account(),
                await basecamp_fastmcp.update_recording_visibility("recording-1", False),
                await basecamp_fastmcp.get_upload_versions("upload-1"),
            )

    account, visibility, versions = asyncio.run(run())
    assert account == {"status": "success", "account": {"id": "account-1"}}
    assert visibility == {"status": "success", "recording": {"id": "recording-1"}}
    assert versions == {
        "status": "success", "versions": [{"action": "created"}], "count": 1
    }
