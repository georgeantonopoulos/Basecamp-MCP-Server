"""Tests for account-wide assignment and schedule reports."""

import asyncio
from unittest.mock import MagicMock, Mock, patch

import basecamp_fastmcp
from basecamp_client import BasecampClient
from mcp_server_cli import MCPServer


def test_account_report_client_uses_documented_endpoints():
    client = BasecampClient.__new__(BasecampClient)
    response = MagicMock(status_code=200)
    response.json.return_value = {"items": []}

    with patch.object(client, "get", return_value=response) as get:
        assert client.get_my_assignments() == {"items": []}
        assert client.get_completed_assignments() == {"items": []}
        assert client.get_due_assignments("due_today") == {"items": []}
        assert client.get_overdue_todos() == {"items": []}
        assert client.get_upcoming_schedule("2026-08-28", "2026-09-04") == {"items": []}

    assert [call.args[0] for call in get.call_args_list] == [
        "my/assignments.json",
        "my/assignments/completed.json",
        "my/assignments/due.json",
        "reports/todos/overdue.json",
        "reports/schedules/upcoming.json",
    ]
    assert get.call_args_list[2].kwargs == {"params": {"scope": "due_today"}}
    assert get.call_args_list[4].kwargs == {
        "params": {"window_starts_on": "2026-08-28", "window_ends_on": "2026-09-04"}
    }


def test_everything_clients_use_cross_project_routes_and_filters():
    client = BasecampClient.__new__(BasecampClient)
    with patch.object(client, "_get_everything_collection", side_effect=[
        [{"id": "message-1"}], [{"id": "comment-1"}], [{"id": "checkin-1"}],
        [{"id": "forward-1"}], [{"id": "file-1"}], [{"bucket": {"id": "p1"}}],
        [{"bucket": {"id": "p2"}}],
    ]) as fetch:
        assert client.get_everything_messages() == [{"id": "message-1"}]
        assert client.get_everything_comments(10) == [{"id": "comment-1"}]
        assert client.get_everything_checkins() == [{"id": "checkin-1"}]
        assert client.get_everything_forwards() == [{"id": "forward-1"}]
        assert client.get_everything_files(25, "pdfs", ["person-1"]) == [{"id": "file-1"}]
        assert client.get_everything_todos("overdue", 50, ["person-1"], "with") == [{"bucket": {"id": "p1"}}]
        assert client.get_everything_cards("not_now", 50, ["person-2"], "without") == [{"bucket": {"id": "p2"}}]

    assert fetch.call_args_list[0].args == ("messages.json",)
    assert fetch.call_args_list[0].kwargs == {"limit": 100, "page": None}
    assert fetch.call_args_list[1].args == ("comments.json",)
    assert fetch.call_args_list[1].kwargs == {"limit": 10, "page": None}
    assert fetch.call_args_list[4].args == ("files.json",)
    assert fetch.call_args_list[4].kwargs == {"limit": 25, "page": None, "params": {"kind": "pdfs", "people_ids[]": ["person-1"]}}
    assert fetch.call_args_list[5].args == ("todos/overdue.json",)
    assert fetch.call_args_list[5].kwargs == {
        "limit": 50, "page": None, "params": {"assignee_ids[]": ["person-1"], "due": "with"}
    }
    assert fetch.call_args_list[6].args == ("cards/not_now.json",)
    assert fetch.call_args_list[6].kwargs == {
        "limit": 50, "page": None,
        "params": {"assignee_ids[]": ["person-2"], "due": "without"},
    }


def test_everything_clients_reject_unknown_filters():
    client = BasecampClient.__new__(BasecampClient)
    for call in (
        lambda: client.get_everything_files(kind="spreadsheets"),
        lambda: client.get_everything_todos(status="all"),
        lambda: client.get_everything_cards(status="all"),
        lambda: client.get_everything_todos(due="tomorrow"),
    ):
        try:
            call()
        except ValueError:
            pass
        else:
            raise AssertionError("invalid Everything filter was accepted")


def test_projects_and_people_follow_pagination_links():
    client = BasecampClient.__new__(BasecampClient)
    client.auth = None
    client.headers = {"User-Agent": "test"}
    projects_page_1 = MagicMock(status_code=200, links={"next": {"url": "https://3.basecampapi.com/6164391/projects"}})
    projects_page_1.json.return_value = [{"id": "project-1"}]
    people_page_1 = MagicMock(status_code=200, links={"next": {"url": "https://3.basecampapi.com/6164391/people"}})
    people_page_1.json.return_value = [{"id": "person-1"}]
    projects_page_2 = MagicMock(status_code=200, links={})
    projects_page_2.json.return_value = [{"id": "project-2"}]
    people_page_2 = MagicMock(status_code=200, links={})
    people_page_2.json.return_value = [{"id": "person-2"}]

    with patch.object(client, "get", side_effect=[projects_page_1, people_page_1]):
        with patch("basecamp_client.requests.get", side_effect=[projects_page_2, people_page_2]):
            assert client.get_projects() == [{"id": "project-1"}, {"id": "project-2"}]
            assert client.get_people() == [{"id": "person-1"}, {"id": "person-2"}]


def test_timeline_clients_use_account_project_and_person_routes():
    client = BasecampClient.__new__(BasecampClient)
    account_response = MagicMock(status_code=200, links={})
    account_response.json.return_value = [{"id": "event-1"}]
    project_response = MagicMock(status_code=200, links={})
    project_response.json.return_value = [{"id": "event-2"}]
    person_response = MagicMock(status_code=200, links={})
    person_response.json.return_value = {
        "person": {"id": "person-1"}, "events": [{"id": "event-3"}]
    }

    with patch.object(client, "get", side_effect=[account_response, project_response, person_response]) as get:
        assert client.get_timeline(5) == [{"id": "event-1"}]
        assert client.get_project_timeline("project-1", 5) == [{"id": "event-2"}]
        assert client.get_person_timeline("person-1", 5)["events"] == [{"id": "event-3"}]

    assert get.call_args_list[0].args == ("reports/progress.json",)
    assert get.call_args_list[1].args == ("projects/project-1/timeline.json",)
    assert get.call_args_list[2].args == ("reports/users/progress/person-1.json",)


def test_everything_limit_stops_link_following_at_the_requested_count():
    client = BasecampClient.__new__(BasecampClient)
    client.auth = None
    client.headers = {"User-Agent": "test"}
    first = MagicMock(status_code=200, links={"next": {"url": "https://3.basecampapi.com/6164391/messages"}})
    first.json.return_value = [{"id": "one"}, {"id": "two"}]

    with patch.object(client, "get", return_value=first):
        with patch("basecamp_client.requests.get") as next_get:
            assert client.get_everything_messages(2) == [{"id": "one"}, {"id": "two"}]

    next_get.assert_not_called()


def test_everything_page_fetches_exactly_one_page():
    client = BasecampClient.__new__(BasecampClient)
    response = MagicMock(status_code=200, links={"next": {"url": "https://3.basecampapi.com/6164391/messages"}})
    response.json.return_value = [{"id": "page-3"}]

    with patch.object(client, "get", return_value=response) as get:
        with patch("basecamp_client.requests.get") as next_get:
            assert client.get_everything_messages(10, 3) == [{"id": "page-3"}]

    get.assert_called_once_with("messages.json", params={"page": 3})
    next_get.assert_not_called()


def test_collection_rejects_external_pagination_links_before_following():
    client = BasecampClient.__new__(BasecampClient)
    client.auth = None
    client.headers = {"User-Agent": "test"}
    response = MagicMock(
        status_code=200,
        links={"next": {"url": "https://evil.example/steal"}},
    )
    response.json.return_value = [{"id": "one"}]

    with patch.object(client, "get", return_value=response):
        with patch("basecamp_client.requests.get") as next_get:
            try:
                client.get_everything_messages()
            except Exception as exc:
                assert "outside Basecamp API" in str(exc)
            else:
                raise AssertionError("external pagination link was followed")

    next_get.assert_not_called()


def test_collection_rejects_non_list_payloads():
    client = BasecampClient.__new__(BasecampClient)
    response = MagicMock(status_code=200, links={})
    response.json.return_value = {"error": "not a collection"}

    with patch.object(client, "get", return_value=response):
        try:
            client.get_everything_messages()
        except Exception as exc:
            assert "expected a list" in str(exc)
        else:
            raise AssertionError("non-list collection payload was accepted")


def test_lineup_marker_clients_use_account_routes():
    client = BasecampClient.__new__(BasecampClient)
    listing = MagicMock(status_code=200, links={})
    listing.json.return_value = [{"id": "marker-1"}]
    created = MagicMock(status_code=201)
    updated = MagicMock(status_code=200)
    deleted = MagicMock(status_code=204)

    with patch.object(client, "_get_paginated_collection", return_value=[{"id": "marker-1"}]) as collect:
        assert client.get_lineup_markers() == [{"id": "marker-1"}]
    with patch.object(client, "post", return_value=created) as post:
        assert client.create_lineup_marker("Launch", "2026-09-01") is True
    with patch.object(client, "put", return_value=updated) as put:
        assert client.update_lineup_marker("marker-1", date="2026-09-02") is True
    with patch.object(client, "delete", return_value=deleted) as delete:
        assert client.delete_lineup_marker("marker-1") is True

    collect.assert_called_once_with("lineup/markers.json")
    post.assert_called_once_with("lineup/markers.json", {"name": "Launch", "date": "2026-09-01"})
    put.assert_called_once_with("lineup/markers/marker-1.json", {"date": "2026-09-02"})
    delete.assert_called_once_with("lineup/markers/marker-1.json")


def test_question_reminders_are_paginated_and_can_be_bounded():
    client = BasecampClient.__new__(BasecampClient)
    reminders = [{"reminder_id": "r1"}, {"reminder_id": "r2"}]

    with patch.object(client, "_get_paginated_collection", return_value=reminders) as get:
        assert client.get_question_reminders(1) == [{"reminder_id": "r1"}]
        assert client.get_question_reminders() == reminders

    assert get.call_args_list[0].args == ("my/question_reminders.json",)
    assert get.call_args_list[0].kwargs == {"limit": 1}
    assert get.call_args_list[1].args == ("my/question_reminders.json",)
    assert get.call_args_list[1].kwargs == {"limit": None}


def test_question_reminders_reject_non_positive_limit():
    client = BasecampClient.__new__(BasecampClient)
    try:
        client.get_question_reminders(0)
    except ValueError as exc:
        assert "limit must be >= 1" in str(exc)
    else:
        raise AssertionError("invalid reminder limit was accepted")


def test_assignment_priority_client_uses_documented_endpoints():
    client = BasecampClient.__new__(BasecampClient)
    response = MagicMock(status_code=204)

    with patch.object(client, "post", return_value=response) as post:
        assert client.prioritize_assignment("recording-1") is True
        assert client.reorder_priority("recording-1", 2) is True
    with patch.object(client, "delete", return_value=response) as delete:
        assert client.deprioritize_assignment("recording-1") is True

    assert post.call_args_list[0].args == ("my/priorities.json", {"id": "recording-1"})
    assert post.call_args_list[1].args == (
        "my/priority_moves.json", {"source_id": "recording-1", "position": 2}
    )
    delete.assert_called_once_with("my/priorities/recording-1.json")


def test_due_assignments_rejects_unknown_scope():
    client = BasecampClient.__new__(BasecampClient)
    try:
        client.get_due_assignments("next_month")
    except ValueError as exc:
        assert "scope must be one of" in str(exc)
    else:
        raise AssertionError("invalid due scope was accepted")


def test_account_report_tools_are_registered_in_both_servers():
    fastmcp_names = set(basecamp_fastmcp.mcp._tool_manager._tools)
    cli_names = {tool["name"] for tool in MCPServer().tools}
    expected = {
        "get_my_assignments", "get_completed_assignments", "get_due_assignments",
        "get_overdue_todos", "get_upcoming_schedule",
        "get_question_reminders",
        "prioritize_assignment", "deprioritize_assignment", "reorder_priority",
        "get_everything_messages", "get_everything_comments", "get_everything_checkins",
        "get_everything_forwards", "get_everything_files", "get_everything_todos",
        "get_everything_cards",
        "get_timeline", "get_project_timeline", "get_person_timeline",
        "get_lineup_markers", "create_lineup_marker", "update_lineup_marker", "delete_lineup_marker",
    }
    assert expected <= fastmcp_names
    assert fastmcp_names == cli_names


def test_account_report_tools_return_structured_results():
    client = Mock()
    client.get_my_assignments.return_value = {"priorities": [], "non_priorities": []}
    client.get_completed_assignments.return_value = [{"id": "todo-1"}]
    client.get_due_assignments.return_value = [{"id": "todo-2"}]
    client.get_overdue_todos.return_value = {"under_a_week_late": []}
    client.get_upcoming_schedule.return_value = {"schedule_entries": []}
    client.get_question_reminders.return_value = [{"reminder_id": "r1"}]
    client.prioritize_assignment.return_value = True
    client.deprioritize_assignment.return_value = True
    client.reorder_priority.return_value = True
    client.get_everything_messages.return_value = [{"id": "message-1"}]
    client.get_everything_comments.return_value = [{"id": "comment-1"}]
    client.get_everything_checkins.return_value = [{"id": "checkin-1"}]
    client.get_everything_forwards.return_value = [{"id": "forward-1"}]
    client.get_everything_files.return_value = [{"id": "file-1"}]
    client.get_everything_todos.return_value = [{"bucket": {"id": "p1"}}]
    client.get_everything_cards.return_value = [{"bucket": {"id": "p1"}}]
    client.get_timeline.return_value = [{"id": "event-1"}]
    client.get_project_timeline.return_value = [{"id": "event-2"}]
    client.get_person_timeline.return_value = {
        "person": {"id": "person-1"}, "events": [{"id": "event-3"}]
    }
    client.get_lineup_markers.return_value = [{"id": "marker-1"}]
    client.create_lineup_marker.return_value = True
    client.update_lineup_marker.return_value = True
    client.delete_lineup_marker.return_value = True

    async def run():
        with patch.object(basecamp_fastmcp, "_get_basecamp_client", return_value=client):
            return (
                await basecamp_fastmcp.get_my_assignments(),
                await basecamp_fastmcp.get_completed_assignments(),
                await basecamp_fastmcp.get_due_assignments("due_today"),
                await basecamp_fastmcp.get_overdue_todos(),
                await basecamp_fastmcp.get_upcoming_schedule("2026-08-28", "2026-09-04"),
                await basecamp_fastmcp.get_question_reminders(5),
                await basecamp_fastmcp.prioritize_assignment("recording-1"),
                await basecamp_fastmcp.deprioritize_assignment("recording-1"),
                await basecamp_fastmcp.reorder_priority("recording-1", 1),
                await basecamp_fastmcp.get_everything_messages(5),
                await basecamp_fastmcp.get_everything_comments(5),
                await basecamp_fastmcp.get_everything_checkins(5),
                await basecamp_fastmcp.get_everything_forwards(5),
                await basecamp_fastmcp.get_everything_files(5, "pdfs", ["person-1"]),
                await basecamp_fastmcp.get_everything_todos("overdue", 5, ["person-1"], "with"),
                await basecamp_fastmcp.get_everything_cards("not_now", 5, ["person-1"], "without"),
                await basecamp_fastmcp.get_timeline(5),
                await basecamp_fastmcp.get_project_timeline("project-1", 5),
                await basecamp_fastmcp.get_person_timeline("person-1", 5),
                await basecamp_fastmcp.get_lineup_markers(),
                await basecamp_fastmcp.create_lineup_marker("Launch", "2026-09-01"),
                await basecamp_fastmcp.update_lineup_marker("marker-1", date="2026-09-02"),
                await basecamp_fastmcp.delete_lineup_marker("marker-1"),
            )

    assignments, completed, due, overdue, upcoming, reminders, prioritized, deprioritized, reordered, messages, comments, checkins, forwards, files, todos, cards, timeline, project_timeline, person_timeline, markers, marker_created, marker_updated, marker_deleted = asyncio.run(run())
    assert assignments["assignments"]["priorities"] == []
    assert completed["count"] == 1
    assert due["assignments"] == [{"id": "todo-2"}]
    assert overdue["overdue"] == {"under_a_week_late": []}
    assert upcoming["upcoming"] == {"schedule_entries": []}
    assert reminders == {
        "status": "success",
        "reminders": [{"reminder_id": "r1"}],
        "count": 1,
    }
    assert prioritized == {"status": "success", "message": "Assignment prioritized"}
    assert deprioritized == {"status": "success", "message": "Assignment deprioritized"}
    assert reordered == {"status": "success", "message": "Assignment priority reordered"}
    assert messages["count"] == 1
    assert comments["comments"] == [{"id": "comment-1"}]
    assert checkins["checkins"] == [{"id": "checkin-1"}]
    assert forwards["forwards"] == [{"id": "forward-1"}]
    assert files["files"] == [{"id": "file-1"}]
    assert todos["filter"] == "overdue"
    assert cards["filter"] == "not_now"
    assert timeline["count"] == 1
    assert project_timeline["events"] == [{"id": "event-2"}]
    assert person_timeline["timeline"]["events"] == [{"id": "event-3"}]
    assert markers["count"] == 1
    assert marker_created["message"] == "Lineup marker created"
    assert marker_updated["message"] == "Lineup marker updated"
    assert marker_deleted["message"] == "Lineup marker deleted"
