# Central hosting design for issue #25

The recommended team setup is one remote MCP server with a separate Basecamp sign-in for each person. This is a design boundary, not an enabled remote mode. The current stdio server and its single configured token file continue to work as before.

## Why a transport switch is insufficient

`basecamp_fastmcp.py` currently builds every Basecamp client from one process-wide token in `token_storage.py`. Starting the same tool catalog over HTTP would give every caller that identity. The configurable token path from #26 helps container deployment, but it does not separate users. Basecamp OAuth access tokens also authorize calls to Basecamp; they do not, by themselves, authenticate a caller to this MCP server.

## Proposed remote path

1. Add an opt-in HTTP entry point using the pinned MCP v1 server's Streamable HTTP transport. Leave the existing stdio entry point and tool names, schemas, and response shaping intact.
2. Require MCP authorization before any tool request. Use a trusted authorization server and verify bearer tokens for this MCP resource. Derive the caller's stable user ID from the verified token, never a tool argument, header supplied by the client, or global environment variable. Serve the protected-resource metadata required by the MCP HTTP authorization specification.
3. Bind each Basecamp OAuth login to that verified user and an explicit Basecamp account. Check OAuth `state` on callback. Store refresh and access tokens under the user/account key in server-side secure storage; rotate them atomically on refresh. Do not fall back to the existing process-wide token file in remote mode.
4. Build the Basecamp client for each request from the verified user/account pair. Reject missing, expired, or revoked credentials for that user only. Keep one user's requests, logs, errors, and downloads from exposing another user's data.
5. Put the HTTP service behind HTTPS with a fixed public origin and registered OAuth callback URL. Reject startup when remote mode lacks its authorization, storage, or public-origin settings.

## Verification gate

- Two users sign in to different Basecamp accounts; each sees only their own projects and files, including under concurrent requests and token refresh.
- An unauthenticated request and a request with a token for another audience fail before tool execution.
- Logout and token revocation affect only the matching user; no request falls back to the legacy token file.
- The same representative read, write, report, and download tools return the same MCP schemas and shaped responses over stdio and HTTP.
- The public HTTPS origin, OAuth callback, proxy headers, and client connection are exercised end to end before deployment.

Implementation needs a deployment URL and the intended team identity provider or authorization service. Those determine the MCP authorization metadata, client registration, and Basecamp callback configuration. A one-shared-Basecamp-identity service would be a separately chosen mode with a different access and audit model; it should not be the implicit fallback.

References: [MCP HTTP authorization specification](https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization), [MCP Python SDK v1 documentation](https://py.sdk.modelcontextprotocol.io/v1/), and this repository's `basecamp_fastmcp.py` and `token_storage.py`.
