"""Tests for schedule endpoint discovery and pagination."""

from unittest.mock import MagicMock, patch

from basecamp_client import BasecampClient


def test_get_schedule_resolves_schedule_from_project_dock():
    client = BasecampClient.__new__(BasecampClient)
    project = {"id": "project-1", "dock": [{"name": "schedule", "id": "schedule-1"}]}
    response = MagicMock(status_code=200)
    response.json.return_value = {"id": "schedule-1", "title": "Schedule"}

    with patch.object(client, "get_project", return_value=project):
        with patch.object(client, "get", return_value=response) as get:
            result = client.get_schedule("project-1")

    assert result == {"id": "schedule-1", "title": "Schedule"}
    get.assert_called_once_with(
        "buckets/project-1/schedules/schedule-1.json"
    )


def test_get_schedule_entries_uses_schedule_id_and_paginates():
    client = BasecampClient.__new__(BasecampClient)
    client.get_schedule = MagicMock(return_value={"id": "schedule-1"})

    with patch.object(client, "_get_paginated_collection", return_value=[
        {"id": "entry-1"},
        {"id": "entry-2"},
    ]) as get_entries:
        result = client.get_schedule_entries("project-1")

    assert result == [{"id": "entry-1"}, {"id": "entry-2"}]
    get_entries.assert_called_once_with(
        "buckets/project-1/schedules/schedule-1/entries.json"
    )


def test_schedule_entry_lifecycle_uses_documented_endpoints():
    client = BasecampClient.__new__(BasecampClient)
    get_response = MagicMock(status_code=200)
    get_response.json.return_value = {"id": "entry-1"}
    create_response = MagicMock(status_code=201)
    create_response.json.return_value = {"id": "entry-2"}
    update_response = MagicMock(status_code=200)
    update_response.json.return_value = {"id": "entry-2", "summary": "Updated"}

    with patch.object(client, "get", side_effect=[get_response, get_response]) as get:
        assert client.get_schedule_entry("project-1", "entry-1") == {"id": "entry-1"}
        assert client.get_schedule_entry_occurrence(
            "project-1", "entry-1", "2026-08-28"
        ) == {"id": "entry-1"}

    with patch.object(client, "get_schedule", return_value={"id": "schedule-1"}):
        with patch.object(client, "post", return_value=create_response) as post:
            assert client.create_schedule_entry(
                "project-1",
                "Planning",
                "2026-08-28T09:00:00Z",
                "2026-08-28T10:00:00Z",
                participant_ids=["person-1"],
                notify=True,
            ) == {"id": "entry-2"}

    with patch.object(client, "put", return_value=update_response) as put:
        assert client.update_schedule_entry(
            "project-1", "entry-2", summary="Updated", all_day=False
        ) == {"id": "entry-2", "summary": "Updated"}

    assert [call.args[0] for call in get.call_args_list] == [
        "buckets/project-1/schedule_entries/entry-1.json",
        "buckets/project-1/schedule_entries/entry-1/occurrences/2026-08-28.json",
    ]
    post.assert_called_once_with(
        "buckets/project-1/schedules/schedule-1/entries.json",
        {
            "summary": "Planning",
            "starts_at": "2026-08-28T09:00:00Z",
            "ends_at": "2026-08-28T10:00:00Z",
            "participant_ids": ["person-1"],
            "notify": True,
        },
    )
    put.assert_called_once_with(
        "buckets/project-1/schedule_entries/entry-2.json",
        {"summary": "Updated", "all_day": False},
    )


def test_update_schedule_entry_requires_a_field():
    client = BasecampClient.__new__(BasecampClient)

    try:
        client.update_schedule_entry("project-1", "entry-1")
    except ValueError as exc:
        assert "at least one schedule entry field" in str(exc)
    else:
        raise AssertionError("empty schedule entry update was accepted")
