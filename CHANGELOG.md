# Changelog

All notable changes to this project are documented here. The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added

- `BASECAMP_MCP_TOKEN_FILE` environment variable to configure the OAuth token file path. Useful for containerized deployments where the application directory is read-only or ephemeral and the token store must live on a mounted volume. When unset, the token file stays at `<project>/oauth_tokens.json` (previous default). See [README — Token Storage Location](README.md#token-storage-location).
