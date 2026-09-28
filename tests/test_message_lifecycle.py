"""Tests for message update and pin lifecycle operations."""

import asyncio
from unittest.mock import Mock, patch

import basecamp_fastmcp
from basecamp_client import BasecampClient


def test_update_message_sends_only_provided_fields():
    client = BasecampClient.__new__(BasecampClient)
    response = Mock(status_code=200)
    response.json.return_value = {"id": "message-1", "subject": "Updated"}

    with patch.object(client, "put", return_value=response) as put:
        result = client.update_message(
            "project-1",
            "message-1",
            subject="Updated",
        )

    assert result == {"id": "message-1", "subject": "Updated"}
    put.assert_called_once_with(
        "buckets/project-1/messages/message-1.json",
        {"subject": "Updated"},
    )


def test_message_pin_operations_use_recording_pin_endpoint():
    client = BasecampClient.__new__(BasecampClient)
    response = Mock(status_code=204)

    with patch.object(client, "post", return_value=response) as post:
        assert client.pin_message("project-1", "message-1") is True
    with patch.object(client, "delete", return_value=response) as delete:
        assert client.unpin_message("project-1", "message-1") is True

    post.assert_called_once_with(
        "buckets/project-1/recordings/message-1/pin.json"
    )
    delete.assert_called_once_with(
        "buckets/project-1/recordings/message-1/pin.json"
    )


def test_fastmcp_message_lifecycle_tools_preserve_clear_shapes():
    client = Mock()
    client.update_message.return_value = {"id": "message-1"}
    client.pin_message.return_value = True
    client.unpin_message.return_value = True

    async def run():
        with patch.object(basecamp_fastmcp, "_get_basecamp_client", return_value=client):
            updated = await basecamp_fastmcp.update_message(
                "project-1", "message-1", subject="Updated"
            )
            pinned = await basecamp_fastmcp.pin_message("project-1", "message-1")
            unpinned = await basecamp_fastmcp.unpin_message("project-1", "message-1")
        return updated, pinned, unpinned

    updated, pinned, unpinned = asyncio.run(run())

    assert updated == {
        "status": "success",
        "message": {"id": "message-1"},
        "result": "Message updated successfully",
    }
    assert pinned == {"status": "success", "message": "Message pinned successfully"}
    assert unpinned == {"status": "success", "message": "Message unpinned successfully"}
