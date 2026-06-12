"""Tests for BasecampClient.download_attachment.

Verifies the critical security property: when the Basecamp blob endpoint
302-redirects to a pre-signed storage host, the OAuth Authorization header
MUST be stripped before issuing the follow-up request. The signed URL does
not need it, and forwarding the token leaks credentials to a third-party
host.
"""

import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from basecamp_client import BasecampClient


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("BASECAMP_ACCOUNT_ID", "6164391")
    monkeypatch.setenv("USER_AGENT", "test-agent (test@example.com)")
    return BasecampClient(
        access_token="dummy-oauth-token",
        auth_mode="oauth",
    )


def _make_response(status_code, headers=None, body=b""):
    resp = MagicMock()
    resp.status_code = status_code
    resp.headers = headers or {}
    # ``response.text`` is read on error paths
    resp.text = body.decode("utf-8", errors="replace") if isinstance(body, bytes) else body
    # iter_content yields raw bytes chunks
    resp.iter_content = MagicMock(return_value=[body] if body else [])
    resp.close = MagicMock()
    return resp


def test_download_attachment_strips_auth_on_cross_host_redirect(client):
    """The Authorization header must NOT travel to storage.app.basecamp.com."""
    initial_url = (
        "https://3.basecampapi.com/6164391/blobs/ed8f26c0-6304-11f1-bfd0-0242ac120004"
        "/download/devTools.png"
    )
    storage_url = (
        "https://storage.app.basecamp.com/abc123/devTools.png?signature=xyz"
    )
    png_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32

    redirect_resp = _make_response(
        302,
        headers={"Location": storage_url},
    )
    download_resp = _make_response(
        200,
        headers={"Content-Type": "image/png", "Content-Length": str(len(png_bytes))},
        body=png_bytes,
    )

    with patch("basecamp_client.requests.get") as mock_get:
        mock_get.side_effect = [redirect_resp, download_resp]
        result = client.download_attachment(initial_url)

    assert mock_get.call_count == 2

    first_call = mock_get.call_args_list[0]
    first_url = first_call.args[0] if first_call.args else first_call.kwargs["url"]
    first_headers = first_call.kwargs.get("headers", {})
    assert first_url == initial_url
    assert first_headers.get("Authorization") == "Bearer dummy-oauth-token"

    second_call = mock_get.call_args_list[1]
    second_url = second_call.args[0] if second_call.args else second_call.kwargs["url"]
    second_headers = second_call.kwargs.get("headers", {})
    assert second_url == storage_url
    assert "Authorization" not in second_headers, (
        "Authorization header leaked to storage host: this exposes the OAuth "
        "Bearer token to a third-party"
    )
    assert second_call.kwargs.get("auth") is None
    # User-Agent must survive — Basecamp's storage host rejects unidentified UAs
    assert "User-Agent" in second_headers

    assert result["data"] == png_bytes
    assert result["content_type"] == "image/png"
    assert result["filename"] == "devTools.png"
    assert result["byte_size"] == len(png_bytes)


def test_download_attachment_rejects_non_basecamp_host(client):
    with pytest.raises(Exception, match="non-basecampapi host"):
        client.download_attachment("https://evil.example.com/blob")


def test_download_attachment_rejects_lookalike_host(client):
    # A suffix match alone would accept attacker-controlled lookalike hosts
    # and leak the Bearer token; only a dot-boundary subdomain is valid.
    with pytest.raises(Exception, match="non-basecampapi host"):
        client.download_attachment("https://evilbasecampapi.com/blob")


def test_download_attachment_respects_max_bytes_via_expected_size(client):
    with pytest.raises(Exception, match="exceeds max_bytes"):
        client.download_attachment(
            "https://3.basecampapi.com/6164391/blobs/k/download/big.bin",
            max_bytes=1024,
            expected_byte_size=2048,
        )


def test_download_attachment_respects_max_bytes_via_content_length(client):
    url = "https://3.basecampapi.com/6164391/blobs/k/download/big.bin"
    big_resp = _make_response(
        200,
        headers={"Content-Type": "application/pdf", "Content-Length": "2048"},
    )
    with patch("basecamp_client.requests.get", return_value=big_resp):
        with pytest.raises(Exception, match="exceeds max_bytes"):
            client.download_attachment(url, max_bytes=1024)


def test_download_attachment_follows_same_host_redirect_with_auth(client):
    """A redirect that stays on *.basecampapi.com keeps the Bearer token."""
    initial_url = "https://3.basecampapi.com/6164391/blobs/k/download/x.png"
    intermediate_url = "https://3.basecampapi.com/6164391/blobs/k/v2/x.png"
    png_bytes = b"\x89PNG\r\n\x1a\n"

    redirect_resp = _make_response(302, headers={"Location": intermediate_url})
    download_resp = _make_response(
        200,
        headers={"Content-Type": "image/png"},
        body=png_bytes,
    )

    with patch("basecamp_client.requests.get") as mock_get:
        mock_get.side_effect = [redirect_resp, download_resp]
        result = client.download_attachment(initial_url)

    assert mock_get.call_count == 2
    second_headers = mock_get.call_args_list[1].kwargs.get("headers", {})
    assert second_headers.get("Authorization") == "Bearer dummy-oauth-token"
    assert result["data"] == png_bytes
