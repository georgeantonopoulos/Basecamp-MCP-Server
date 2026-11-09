"""Tests for automatic check-ins reads and compatibility responses."""

import asyncio
from unittest.mock import MagicMock, Mock, patch

import basecamp_fastmcp
from basecamp_client import BasecampClient
from mcp_server_cli import MCPServer


def test_checkin_client_resolves_questionnaire_and_paginates_questions():
    client = BasecampClient.__new__(BasecampClient)
    client.get_project = MagicMock(
        return_value={"dock": [{"name": "questionnaire", "id": "questionnaire-1"}]}
    )
    client._get_paginated_collection = MagicMock(return_value=[{"id": "question-1"}])

    assert client.get_questions("project-1") == [{"id": "question-1"}]
    client._get_paginated_collection.assert_called_once_with(
        "buckets/project-1/questionnaires/questionnaire-1/questions.json"
    )


def test_checkin_client_uses_documented_detail_endpoints():
    client = BasecampClient.__new__(BasecampClient)
    response = MagicMock(status_code=200)
    response.json.return_value = {"id": "detail-1"}

    with patch.object(client, "get", return_value=response) as get:
        assert client.get_questionnaire("project-1", "questionnaire-1") == {"id": "detail-1"}
        assert client.get_question("project-1", "question-1") == {"id": "detail-1"}
        assert client.get_question_answer("project-1", "answer-1") == {"id": "detail-1"}

    assert [call.args[0] for call in get.call_args_list] == [
        "buckets/project-1/questionnaires/questionnaire-1.json",
        "buckets/project-1/questions/question-1.json",
        "buckets/project-1/question_answers/answer-1.json",
    ]


def test_checkin_tools_are_registered_in_both_servers():
    fastmcp_names = set(basecamp_fastmcp.mcp._tool_manager._tools)
    cli_names = {tool["name"] for tool in MCPServer().tools}

    assert {
        "get_daily_check_ins",
        "get_questionnaire",
        "get_questions",
        "get_question",
        "get_question_answers",
        "get_question_answer",
    } <= fastmcp_names
    assert fastmcp_names == cli_names


def test_checkin_tools_return_accurate_shapes_and_preserve_alias():
    client = Mock()
    client.get_daily_check_ins.return_value = [{"id": "question-1"}]
    client.get_question_answers.return_value = [{"id": "answer-1"}]
    client.get_questionnaire.return_value = {"id": "questionnaire-1"}
    client.get_questions.return_value = [{"id": "question-1"}]
    client.get_question.return_value = {"id": "question-1"}
    client.get_question_answer.return_value = {"id": "answer-1"}

    async def run():
        with patch.object(basecamp_fastmcp, "_get_basecamp_client", return_value=client):
            return (
                await basecamp_fastmcp.get_daily_check_ins("project-1"),
                await basecamp_fastmcp.get_question_answers("project-1", "question-1"),
                await basecamp_fastmcp.get_questionnaire("project-1"),
                await basecamp_fastmcp.get_questions("project-1"),
                await basecamp_fastmcp.get_question("project-1", "question-1"),
                await basecamp_fastmcp.get_question_answer("project-1", "answer-1"),
            )

    daily, answers, questionnaire, questions, question, answer = asyncio.run(run())
    assert daily["questions"] == daily["campfire_lines"] == [{"id": "question-1"}]
    assert answers["answers"] == answers["campfire_lines"] == [{"id": "answer-1"}]
    assert questionnaire == {"status": "success", "questionnaire": {"id": "questionnaire-1"}}
    assert questions == {"status": "success", "questions": [{"id": "question-1"}], "count": 1}
    assert question == {"status": "success", "question": {"id": "question-1"}}
    assert answer == {"status": "success", "answer": {"id": "answer-1"}}
