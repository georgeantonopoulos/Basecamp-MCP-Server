"""Tests for cross-project card-table wormholes and moves."""

import asyncio
from unittest.mock import MagicMock, Mock, patch

import basecamp_fastmcp
from basecamp_client import BasecampClient
from mcp_server_cli import MCPServer


def test_move_card_supports_optional_position_without_breaking_basic_move():
    client = BasecampClient.__new__(BasecampClient)
    response = MagicMock(status_code=204)
    with patch.object(client, "post", return_value=response) as post:
        assert client.move_card("project-1", "card-1", "column-1") is True
        assert client.move_card("project-1", "card-1", "column-1", 2) is True
    assert post.call_args_list[0].args == (
        "buckets/project-1/card_tables/cards/card-1/moves.json",
        {"column_id": "column-1"},
    )
    assert post.call_args_list[1].args == (
        "buckets/project-1/card_tables/cards/card-1/moves.json",
        {"column_id": "column-1", "position": 2},
    )


def test_wormhole_client_uses_documented_routes_and_payloads():
    client = BasecampClient.__new__(BasecampClient)
    created = MagicMock(status_code=201)
    created.json.return_value = {"id": "wormhole-1"}
    updated = MagicMock(status_code=200)
    updated.json.return_value = {"id": "wormhole-1"}
    deleted = MagicMock(status_code=204)
    with patch.object(client, "post", return_value=created) as post:
        assert client.create_card_table_wormhole(
            "project-1", "table-1", "column-2"
        )["id"] == "wormhole-1"
    with patch.object(client, "put", return_value=updated) as put:
        assert client.update_card_table_wormhole(
            "project-1", "wormhole-1", "column-3"
        )["id"] == "wormhole-1"
    with patch.object(client, "delete", return_value=deleted) as delete:
        assert client.delete_card_table_wormhole("project-1", "wormhole-1") is True

    post.assert_called_once_with(
        "buckets/project-1/card_tables/table-1/wormholes.json",
        {"destination_recording_id": "column-2"},
    )
    put.assert_called_once_with(
        "buckets/project-1/card_tables/wormholes/wormhole-1.json",
        {"destination_recording_id": "column-3"},
    )
    delete.assert_called_once_with(
        "buckets/project-1/card_tables/wormholes/wormhole-1.json"
    )


def test_wormhole_tools_are_registered_and_structured():
    expected = {
        "create_card_table_wormhole",
        "update_card_table_wormhole",
        "delete_card_table_wormhole",
    }
    fastmcp_names = set(basecamp_fastmcp.mcp._tool_manager._tools)
    cli_names = {tool["name"] for tool in MCPServer().tools}
    assert expected <= fastmcp_names
    assert fastmcp_names == cli_names

    client = Mock()
    client.create_card_table_wormhole.return_value = {"id": "wormhole-1"}
    client.move_card.return_value = True

    async def run():
        with patch.object(basecamp_fastmcp, "_get_basecamp_client", return_value=client):
            return (
                await basecamp_fastmcp.create_card_table_wormhole(
                    "project-1", "table-1", "column-2"
                ),
                await basecamp_fastmcp.move_card(
                    "project-1", "card-1", "wormhole-1", position=1
                ),
            )

    wormhole, moved = asyncio.run(run())
    assert wormhole == {
        "status": "success",
        "wormhole": {"id": "wormhole-1"},
        "message": "Wormhole created",
    }
    assert moved == {"status": "success", "message": "Card moved to column wormhole-1"}
