# Official Python SDK adapter spike

This is the bounded follow-up for [issue #29](https://github.com/georgeantonopoulos/Basecamp-MCP-Server/issues/29). It does not change the production client or MCP tool contracts.

## Recommendation

Keep `BasecampClient` as the production path for now. An SDK adapter is promising, but a direct replacement would drop Python 3.10 support and the current bounded download behavior. Any future adapter must preserve existing tool names, input schemas, complete response envelopes, and the shared `payload_shaping.py` behavior in both server paths.

## Offline probe (SDK 0.14.0)

The official `basecamp-sdk` package was installed in a separate Python 3.12 environment. An `httpx.MockTransport` supplied synthetic API responses; no Basecamp account or token was used.

| Path | Result | Adapter work still needed |
| --- | --- | --- |
| Project read and pagination | `projects.list()` followed the `Link` header and returned both pages. Its list could be passed to `payload_shaping.projects_response`. | Preserve the existing summary/full controls, filters, caps, and response envelope. |
| To-do write | `todos.create()` sent the expected content and returned the created record. | Preserve this server's argument names, validation, and response format. |
| Overdue report | `reports.overdue()` returned the report payload. | Preserve the current report shaping and assignee filter. |
| OAuth refresh | `OAuthTokenProvider` refreshed an expired Launchpad token and called `on_refresh` with the new tokens and expiry. | Adapt that callback to this repo's token storage and expiry format; do not use a static provider for expiring tokens. |
| Error handling | A 404 raised a typed `NotFoundError` with HTTP status. | Map SDK exceptions to the existing MCP error contract on both server paths. |
| Upload download | `uploads.download()` fetched metadata, followed the signed redirect, and returned bytes and filename. | Keep the current `max_bytes` limit and metadata fields. The SDK helper has no `max_bytes` argument and returns the whole body. |

The package requires Python 3.11 or later; this repository's test matrix includes Python 3.10. Do not add the SDK to production requirements until the supported Python policy is decided. The SDK is still marked Beta and has documented response changes between recent versions, so pin any experimental version and compare complete responses before rollout.

This probe used mocked HTTP. It does not prove behavior against a live Basecamp account, real OAuth callback, signed storage service, or a deployed MCP client. A production adapter needs those checks, plus the existing maintained test suite, before switching any tool.

Sources: [official Python SDK](https://github.com/basecamp/basecamp-sdk/tree/main/python), [SDK migration notes](https://github.com/basecamp/basecamp-sdk/blob/main/MIGRATING.md), and the repository's own `payload_shaping.py` and `basecamp_client.py`.
