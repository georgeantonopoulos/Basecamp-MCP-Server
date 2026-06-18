# Changelog

All notable changes to this project are documented here. The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added

- `publish` option for `create_message` and `create_document`. The tools still
  publish immediately by default, and callers can pass `publish: false` to omit
  `status: "active"` and create a Basecamp draft instead.
- `create_draft_message` and `create_draft_document` MCP tools as explicit,
  discoverable draft-first wrappers for agents that may miss optional flags.
- `download_upload` MCP tool for retrieving the binary content of a vault `Upload` recording (PDF, image, document, …) directly through MCP. Returns the file as `ImageContent` for image MIME types and as an `EmbeddedResource` (`BlobResourceContents`) for everything else, so the MCP host can forward the blob to the model and the file is read natively (PDF tables, images, OCR) without an out-of-band fetch. Caps the payload via `max_bytes` (default 25 MB) so the MCP transport and model context are not stressed by huge files.
- `download_attachment` MCP tool for retrieving inline comment/message attachments. Pass the `content_attachments[].download_url` returned by `get_comments` / `get_messages` and receive the file as MCP `ImageContent` (image MIME types) or `EmbeddedResource` (everything else). Required because inline attachments are `Attachment` objects, not `Upload` recordings — the `/uploads/{id}` endpoint returns 404 for their IDs. The implementation walks the 302 redirect to the pre-signed storage host manually and strips the OAuth `Authorization` header on the cross-host hop to avoid leaking the Bearer token. Honours a `max_bytes` guard (default 25 MB) via the caller-supplied `byte_size`, `Content-Length`, and a streaming cutoff.

### Fixed

- Todo and card completion helpers now treat Basecamp's successful `204 No Content`
  responses as completed instead of raising an error.
- Card-step completion now uses Basecamp's documented card-table step completions
  endpoint with `completion: "on"` / `"off"`.

### Notes

- `download_upload` and `download_attachment` rely on the MCP host (the client application) forwarding `ImageContent` / `EmbeddedResource` blocks to the model. As of June 2026, Claude Code (CLI) supports both fully, including `application/pdf`. Claude Desktop / claude.ai web rejects non-image `EmbeddedResource` blocks with `"Resources of type 'application/pdf' are not currently supported"` — the bytes arrive at the host but never reach the model. No server-side workaround possible.
- `BASECAMP_MCP_TOKEN_FILE` environment variable to configure the OAuth token file path. Useful for containerized deployments where the application directory is read-only or ephemeral and the token store must live on a mounted volume. When unset, the token file stays at `<project>/oauth_tokens.json` (previous default). See [README — Token Storage Location](README.md#token-storage-location).
