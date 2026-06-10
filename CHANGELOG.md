# Changelog

All notable changes to this project are documented here. The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added

- `download_upload` MCP tool for retrieving the binary content of a vault `Upload` recording (PDF, image, document, …) directly through MCP. Returns the file as `ImageContent` for image MIME types and as an `EmbeddedResource` (`BlobResourceContents`) for everything else, so the MCP host can forward the blob to the model and the file is read natively (PDF tables, images, OCR) without an out-of-band fetch. Caps the payload via `max_bytes` (default 25 MB) so the MCP transport and model context are not stressed by huge files.
- `download_attachment` MCP tool for retrieving inline comment/message attachments. Pass the `content_attachments[].download_url` returned by `get_comments` / `get_messages` and receive the file as MCP `ImageContent` (image MIME types) or `EmbeddedResource` (everything else). Required because inline attachments are `Attachment` objects, not `Upload` recordings — the `/uploads/{id}` endpoint returns 404 for their IDs. The implementation walks the 302 redirect to the pre-signed storage host manually and strips the OAuth `Authorization` header on the cross-host hop to avoid leaking the Bearer token. Honours a `max_bytes` guard (default 25 MB) via the caller-supplied `byte_size`, `Content-Length`, and a streaming cutoff.
- `BASECAMP_MCP_TOKEN_FILE` environment variable to configure the OAuth token file path. Useful for containerized deployments where the application directory is read-only or ephemeral and the token store must live on a mounted volume. When unset, the token file stays at `<project>/oauth_tokens.json` (previous default). See [README — Token Storage Location](README.md#token-storage-location).
