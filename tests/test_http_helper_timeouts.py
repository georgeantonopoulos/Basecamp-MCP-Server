"""Regression tests for the Basecamp client's shared request timeout."""

from unittest.mock import patch

import pytest

from basecamp_client import BasecampClient


@pytest.fixture
def client():
    instance = BasecampClient.__new__(BasecampClient)
    instance.base_url = "https://3.basecampapi.com/123"
    instance.auth = object()
    instance.headers = {"User-Agent": "test-agent"}
    return instance


@pytest.mark.parametrize(
    ("verb", "method_name", "expected_kwargs"),
    [
        ("get", "get", {"params": {"page": 2}}),
        ("post", "post", {"json": {"name": "New"}}),
        ("put", "put", {"json": {"name": "Updated"}}),
        ("delete", "delete", {}),
        ("patch", "patch", {"json": {"status": "active"}}),
    ],
)
def test_http_helpers_forward_shared_timeout(client, verb, method_name,
                                             expected_kwargs):
    with patch(f"basecamp_client.requests.{verb}") as request:
        if verb == "get":
            client.get("resource.json", params=expected_kwargs["params"])
        elif verb == "delete":
            client.delete("resource.json")
        else:
            getattr(client, method_name)("resource.json", expected_kwargs["json"])

    request.assert_called_once_with(
        "https://3.basecampapi.com/123/resource.json",
        auth=client.auth,
        headers=client.headers,
        timeout=(10, 300),
        **expected_kwargs,
    )
