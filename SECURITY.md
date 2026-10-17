# Security Policy

## Supported versions

| Version | Supported |
|---|---|
| 1.3.x (latest) | Yes |
| Earlier than 1.3 | No. Please upgrade |

Fixes are released as a new patch version. Plugin hosts update installed copies when the version changes.

## Reporting a vulnerability

**Please do not open a public issue for a security problem.**

1. Use GitHub private vulnerability reporting: the repository's **Security** tab → **Report a vulnerability**.
2. Include the affected version, the component (MCP server, eval script, router, a skill or a manifest), steps to reproduce, and the impact you expect. Do not include real API keys or personal data; use placeholders.
3. If private reporting is unavailable, open an issue that says only that you have a security report and asks for a private channel.

What to expect (best effort; Model Finder is maintained without a paid support plan):

- Acknowledgement within 5 business days.
- An initial assessment within 10 business days.
- A fix or mitigation released as soon as practical, with credit to the reporter in the changelog unless you prefer otherwise.
- Please allow us to release a fix before you disclose details publicly. We aim to coordinate disclosure within 90 days.

**Safe harbour.** We will not pursue action against good-faith research that stays within these rules: test only on your own installations, do not access other people's data, do not degrade services, and report promptly.

## In scope

- The local MCP server (`mcp/server.py`, and the `model-finder-mcp` PyPI package)
- The scripts in `skills/*/scripts/` and the generated `router.py`
- The skills' instructions (for example instructions that could make an assistant leak data or ignore the user)
- Plugin and extension manifests, and the release workflow

Out of scope: vulnerabilities in the AI assistants, IDEs, model providers, marketplaces or registries themselves. Report those to their owners.

## Security design

- **Keys**: read only from environment variables named in configs (`api_key_env`). Configs containing `api_key`, `key`, `token`, `secret`, or `authorization` fields are rejected. Keys are never printed or written to disk; provider error text is scrubbed of the key value.
- **Transport**: HTTPS required; plain HTTP is allowed only for loopback hosts (local runtimes). Endpoints with embedded credentials, query strings, or fragments are rejected.
- **Redirects**: refused, so credentials are never forwarded to another host. Auth headers are also set as unredirected headers.
- **Limits**: response bodies capped at 10 MiB, regex patterns at 500 chars (searched over at most 100,000 chars), inputs at 200,000 chars, candidates at 10, examples at 500.
- **No dependencies**: scripts use the Python standard library only, so there is no third-party supply chain to compromise.
- **No side effects**: nothing is deployed, no active model or setting is changed, and results stay in local files the user chooses.
- **Data**: evaluation examples are sent to every configured provider. The eval skill requires a dry run and explicit user consent before any paid call, and recommends redacted or synthetic examples.
- **Personal data and secrets guard**: inputs are scanned before sending. Secrets are always blocked; personal data (Aadhaar, PAN, cards, email, UPI, Indian mobile) blocks the run unless explicitly allowed, and the decision is recorded. Detection reports categories and counts only. The router supports `pii_policy: block | warn | off`. See [DATA-PROTECTION.md](DATA-PROTECTION.md) for the DPDP Act mapping.
- **MCP server** (`mcp/server.py`): local stdio only. It opens no network connections, reads no API keys, writes no files and never logs tool arguments (an unexpected internal error logs only its type and code location to stderr). All ten tools are read-only and declare `title`, `readOnlyHint: true`, `destructiveHint: false`, `idempotentHint: true` and `openWorldHint: false`. Messages are capped at 8 MiB and text inputs at 1,000,000 characters; unknown arguments are rejected. Repository tools resolve paths inside the workspace roots (client-shared roots, else `MODEL_FINDER_ROOT`, else the working directory; a host that starts the server in the plugin folder must pass an explicit project path) and refuse a filesystem root or the home directory (and, when the host gives no workspace, the plugin folder). They do not follow symlinks, skip secret-like files (`.env*`, keys, certificates, credential and token files) and dependency/build folders, cap files at 1 MB and 5,000 files, and never return line content from the audit. Drafted eval examples containing detected personal data or secrets are dropped.
- **Skills**: plain Markdown instructions with no hidden, encoded or remotely fetched instructions. They tell the assistant never to change the user's model, deploy, or send data to a provider without explicit approval.
- **Build and release supply chain**: GitHub Actions are pinned to commit SHAs and checkout does not persist credentials. Releases publish to PyPI with trusted publishing (no stored PyPI token) and to the MCP Registry with GitHub OIDC. The PyPI package has no dependencies.
