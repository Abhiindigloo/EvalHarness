# Security

## Design

- **Keys**: read only from environment variables named in configs (`api_key_env`). Configs containing `api_key`, `key`, `token`, `secret`, or `authorization` fields are rejected. Keys are never printed or written to disk; provider error text is scrubbed of the key value.
- **Transport**: HTTPS required; plain HTTP is allowed only for loopback hosts (local runtimes). Endpoints with embedded credentials, query strings, or fragments are rejected.
- **Redirects**: refused, so credentials are never forwarded to another host. Auth headers are also set as unredirected headers.
- **Limits**: response bodies capped at 10 MiB, regex patterns at 500 chars (searched over at most 100,000 chars), inputs at 200,000 chars, candidates at 10, examples at 500.
- **No dependencies**: scripts use the Python standard library only, so there is no third-party supply chain to compromise.
- **No side effects**: nothing is deployed, no active model or setting is changed, and results stay in local files the user chooses.
- **Data**: evaluation examples are sent to every configured provider. The eval skill requires a dry run and explicit user consent before any paid call, and recommends redacted or synthetic examples.
- **Personal data and secrets guard**: inputs are scanned before sending. Secrets are always blocked; personal data (Aadhaar, PAN, cards, email, UPI, Indian mobile) blocks the run unless explicitly allowed, and the decision is recorded. Detection reports categories and counts only. The router supports `pii_policy: block | warn | off`. See [DATA-PROTECTION.md](DATA-PROTECTION.md) for the DPDP Act mapping.

- **MCP server** (`mcp/server.py`): local stdio only. It opens no network connections, reads no API keys, and writes no files; all ten tools are read-only and marked `readOnlyHint`. Messages are capped at 8 MiB and text inputs at 1,000,000 characters. Repository tools resolve paths inside the workspace roots (client-shared roots, else `MODEL_FINDER_ROOT`, else the working directory) and refuse a filesystem root or home directory. They do not follow symlinks, skip secret-like files (`.env*`, keys, certificates, credential and token files) and dependency/build folders, cap files at 1 MB and 5,000 files, and never return line content from the audit. Drafted eval examples containing detected personal data or secrets are dropped.

- **Build and release supply chain**: GitHub Actions are pinned to commit SHAs and checkout does not persist credentials. Releases publish to PyPI with trusted publishing (no stored PyPI token) and to the MCP Registry with GitHub OIDC. The PyPI package has no dependencies.

## Reporting a vulnerability

Use the repository's private vulnerability reporting (Security tab). If unavailable, open an issue asking for a private contact channel, without exploit details or secrets.
