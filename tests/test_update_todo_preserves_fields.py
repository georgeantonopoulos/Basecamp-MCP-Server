#!/usr/bin/env python3
"""Tests that update_todo() re-sends existing values for omitted fields.

Basecamp's to-do PUT clears any parameter absent from the request:

    "Omitting a parameter will clear its value, for example, empty/missing
     assignee_ids clears existing assignees. Pass all existing parameters in
     addition to those being updated."
    -- https://github.com/basecamp/bc3-api/blob/master/sections/todos.md

So update_todo() fetches the to-do and merges the caller's fields over its
current values, rather than sending only what the caller supplied.
"""

import os
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from basecamp_client import BasecampClient


def _client():
    """Return a BasecampClient with dummy OAuth credentials for unit tests."""
    return BasecampClient(
        access_token='token', account_id='123',
        user_agent='test-agent', auth_mode='oauth',
    )


EXISTING_TODO = {
    'id': 9,
    'content': 'Original title',
    'description': '<div>Original description</div>',
    'assignees': [{'id': 111}, {'id': 222}],
    'completion_subscribers': [{'id': 333}],
    'due_on': '2026-01-31',
    'starts_on': '2026-01-01',
}

ENDPOINT = 'buckets/1/todos/9.json'


def _put_response():
    response = Mock()
    response.status_code = 200
    response.json.return_value = {'id': 9}
    response.text = ''
    return response


class TestUpdateTodoPreservesFields(unittest.TestCase):

    def _update(self, **kwargs):
        """Run update_todo against the fixture, returning the PUT payload."""
        client = _client()
        with patch.object(client, 'get_todo', return_value=dict(EXISTING_TODO)), \
                patch.object(client, 'put', return_value=_put_response()) as put:
            client.update_todo('1', '9', **kwargs)
        put.assert_called_once()
        endpoint, payload = put.call_args[0]
        self.assertEqual(endpoint, ENDPOINT)
        return payload

    def test_changing_only_content_preserves_everything_else(self):
        """The regression this guards: a title edit must not wipe assignees."""
        payload = self._update(content='New title')

        self.assertEqual(payload['content'], 'New title')
        self.assertEqual(payload['assignee_ids'], [111, 222])
        self.assertEqual(payload['completion_subscriber_ids'], [333])
        self.assertEqual(payload['due_on'], '2026-01-31')
        self.assertEqual(payload['starts_on'], '2026-01-01')
        self.assertEqual(payload['description'], '<div>Original description</div>')

    def test_changing_only_due_date_preserves_content_and_assignees(self):
        payload = self._update(due_on='2026-12-25')

        self.assertEqual(payload['due_on'], '2026-12-25')
        self.assertEqual(payload['content'], 'Original title')
        self.assertEqual(payload['assignee_ids'], [111, 222])

    def test_empty_list_still_clears_assignees(self):
        """Passing [] is an explicit clear, not an omission."""
        payload = self._update(assignee_ids=[])
        self.assertEqual(payload['assignee_ids'], [])

    def test_empty_string_still_clears_due_date(self):
        payload = self._update(due_on='')
        self.assertEqual(payload['due_on'], '')

    def test_notify_omitted_unless_supplied(self):
        self.assertNotIn('notify', self._update(content='x'))
        self.assertTrue(self._update(content='x', notify=True)['notify'])

    def test_handles_todo_with_no_assignees_or_dates(self):
        client = _client()
        sparse = {'id': 9, 'content': 'Bare', 'description': None,
                  'assignees': [], 'completion_subscribers': [],
                  'due_on': None, 'starts_on': None}
        with patch.object(client, 'get_todo', return_value=sparse), \
                patch.object(client, 'put', return_value=_put_response()) as put:
            client.update_todo('1', '9', content='Renamed')
        payload = put.call_args[0][1]
        self.assertEqual(payload['assignee_ids'], [])
        self.assertEqual(payload['description'], '')
        self.assertIsNone(payload['due_on'])

    def test_no_fields_raises_without_calling_the_api(self):
        """The pre-existing ValueError contract is kept, and costs no request."""
        client = _client()
        with patch.object(client, 'get_todo') as get_todo, \
                patch.object(client, 'put') as put:
            with self.assertRaises(ValueError):
                client.update_todo('1', '9')
        get_todo.assert_not_called()
        put.assert_not_called()


if __name__ == '__main__':
    unittest.main()
