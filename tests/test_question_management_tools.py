"""Tests for automatic check-in question lifecycle operations."""

import asyncio
from unittest.mock import MagicMock, Mock, patch

import basecamp_fastmcp
from basecamp_client import BasecampClient
from mcp_server_cli import MCPServer


def test_question_client_uses_documented_routes_and_payloads():
    client = BasecampClient.__new__(BasecampClient)
    detail = MagicMock(status_code=200)
    detail.json.return_value = {"id": "question-1"}
    created = MagicMock(status_code=201)
    created.json.return_value = {"id": "question-1"}
    updated = MagicMock(status_code=200)
    updated.json.return_value = {"id": "question-1", "paused": False}

    schedule = {"frequency": "every_day", "time_of_day": "9:00am", "days": ["1"]}
    with patch.object(client, "post", side_effect=[created, updated]) as post:
        assert client.create_question("questionnaire-1", "Daily update", schedule)["id"] == "question-1"
        assert client.pause_question("question-1")["paused"] is False
    with patch.object(client, "put", side_effect=[updated, updated]) as put:
        assert client.update_question("question-1", title="Weekly update")["id"] == "question-1"
        assert client.update_question_notification_settings(
            "question-1", responding=True, subscribed=False
        )["id"] == "question-1"
    with patch.object(client, "delete", return_value=updated) as delete:
        assert client.resume_question("question-1")["paused"] is False
    with patch.object(client, "get", return_value=detail) as get:
        assert client.get_question("project-1", "question-1")["id"] == "question-1"

    post.assert_any_call(
        "questionnaires/questionnaire-1/questions.json",
        {"question": {"title": "Daily update", "schedule": schedule}},
    )
    post.assert_any_call("questions/question-1/pause.json")
    assert put.call_args_list[0].args == (
        "questions/question-1.json", {"question": {"title": "Weekly update"}}
    )
    assert put.call_args_list[1].args == (
        "questions/question-1/notification_settings.json",
        {"responding": True, "subscribed": False},
    )
    delete.assert_called_once_with("questions/question-1/pause.json")
    get.assert_called_once_with("buckets/project-1/questions/question-1.json")


def test_question_client_validates_mutations():
    client = BasecampClient.__new__(BasecampClient)
    for call in (
        lambda: client.create_question("q-1", "", {}),
        lambda: client.create_question("q-1", "Question", {}),
        lambda: client.update_question("question-1"),
        lambda: client.update_question_notification_settings("question-1"),
        lambda: client.update_question_notification_settings("question-1", responding="yes"),
    ):
        try:
            call()
        except ValueError:
            pass
        else:
            raise AssertionError("invalid question mutation was accepted")


def test_question_answerers_use_flat_route_and_limit():
    client = BasecampClient.__new__(BasecampClient)
    with patch.object(client, "_get_paginated_collection", return_value=[{"id": "person-1"}]) as collect:
        assert client.get_question_answerers("question-1", 10) == [{"id": "person-1"}]
    collect.assert_called_once_with(
        "questions/question-1/answers/by.json", limit=10
    )


def test_question_management_tools_are_registered_and_return_structured_results():
    expected = {
        "create_question", "update_question", "pause_question", "resume_question",
        "update_question_notification_settings", "get_question_answerers",
    }
    fastmcp_names = set(basecamp_fastmcp.mcp._tool_manager._tools)
    cli_names = {tool["name"] for tool in MCPServer().tools}
    assert expected <= fastmcp_names
    assert fastmcp_names == cli_names

    client = Mock()
    client.create_question.return_value = {"id": "question-1"}
    client.pause_question.return_value = {"paused": True}
    client.get_question_answerers.return_value = [{"id": "person-1"}]
    client.update_question_notification_settings.return_value = {"responding": True}

    async def run():
        with patch.object(basecamp_fastmcp, "_get_basecamp_client", return_value=client):
            return (
                await basecamp_fastmcp.create_question("q-1", "Daily", {"frequency": "every_day"}),
                await basecamp_fastmcp.pause_question("question-1"),
                await basecamp_fastmcp.update_question_notification_settings(
                    "question-1", responding=True
                ),
                await basecamp_fastmcp.get_question_answerers("question-1"),
            )

    created, paused, settings, answerers = asyncio.run(run())
    assert created["status"] == "success" and created["question"]["id"] == "question-1"
    assert paused == {
        "status": "success", "question": {"paused": True}, "message": "Question paused"
    }
    assert settings == {"status": "success", "settings": {"responding": True}}
    client.update_question_notification_settings.assert_called_once_with(
        "question-1", True, None
    )
    assert answerers == {
        "status": "success", "answerers": [{"id": "person-1"}], "count": 1
    }
