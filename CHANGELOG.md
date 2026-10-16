# Changelog

## 1.3.2 (2026-10-16)

Found by installing the plugin in each host CLI ("test all").

- **Every repository link was misspelt** (`EvalHarnes` instead of `EvalHarness`), so all install commands and listing links (homepage, support, privacy, terms, Codex marketplace source) pointed to a repository that does not exist. Fixed in all manifests, skills and docs; a new test fails on any other repo name.
- **Codex: the MCP server never started.** A root `plugin.json` makes Codex load the plugin in Agent Plugins format, which reads `mcp.json` (no leading dot) and ignores `.mcp.json`. Added `mcp.json` with `type: stdio` and `${PLUGIN_ROOT}`. Copilot CLI uses it too.
- **Codex: the audit scanned the plugin instead of the user's project.** Agent Plugins hosts start servers in the plugin folder and send no workspace. The server now detects this and asks for an absolute `path` (the agent's working directory) instead of auditing itself; the plugin folder, `/` and the home directory are refused.
- Codex ignored the listing logo and composer icon because their paths did not start with `./`. Fixed in `plugin.json`.
- `modelfinder_estimate_memory` errors now name the tool's arguments (`params_b`, `kv_heads`) instead of CLI flags (`params-b`).
- README: the Codex install command is `codex plugin add`, not `codex plugin install`; Copilot CLI install command added.
- README: per-IDE MCP setup. VS Code's `.vscode/mcp.json` needs a top-level `servers` key (the old generic `mcpServers` snippet failed there); VS Code and Cursor snippets set `MODEL_FINDER_ROOT` to `${workspaceFolder}`.
- Tests: 39 (new: plugin-folder workspace handling, Agent Plugins `mcp.json` and asset paths).

## 1.3.1 (2026-10-16)

- Removed every dependency on the separate website repository, which has moved to a new owner.
- Added PRIVACY.md, TERMS.md and SUPPORT.md (drafts for legal review); all listing links (homepage, support, privacy, terms) now point to this repository.
- Rewrote the find-model analytics guidance so it no longer refers to the website's analytics page.
- DATA-PROTECTION.md now covers the repository and issues instead of the website.
- New test fails if any file references the old website, or if a listing link points to a file that does not exist.
- **MCP server brought to MCP builder conventions** (breaking for tool names; nothing had been published):
  - Tools renamed with a `modelfinder_` prefix so they cannot collide with other servers; server name `model_finder_mcp`.
  - `response_format`: markdown summaries by default, full JSON on request; JSON is always in `structuredContent`.
  - `outputSchema` on every tool (protocol 2025-06-18 and later), validated by the official MCP Python SDK client.
  - Pagination (`limit`, `offset`, `has_more`, `next_offset`) for `modelfinder_audit_models` and `modelfinder_draft_eval_examples`; stable draft ids across pages.
  - Filters for the audit: `provider_family`, `hard_coded_only`.
  - Every input field described; unknown arguments rejected with the valid list; errors prefixed `Error:` with a next step.
  - `--help` and `--version` on `mcp/server.py`; cost results rounded to remove floating-point noise.
- Evaluation: `evaluations/` holds a fixture repository and 10 verified questions for testing how well an AI agent uses the tools.

## 1.3.0 (2026-10-14)

- **Local MCP server** (`mcp/server.py`): stdio, Python standard library only, no network access, no key access, no file writes. Ten read-only tools: `audit_models`, `draft_eval_examples`, `create_eval_config`, `validate_eval_config`, `check_output`, `rank_eval_results`, `generate_routing`, `estimate_cost`, `estimate_memory`, `scan_sensitive_data`. Negotiates MCP protocol revisions 2024-11-05 to 2025-11-25 and uses client roots to find the workspace.
- **Model audit** (`repo_scan.py audit`): model ID literals with provider family, route hints (Bedrock, Vertex AI, Azure, OpenRouter), file:line locations, hard-coded vs environment-variable defaults, `-latest` aliases, and AI SDKs from imports and dependency files. Never returns line content.
- **Eval drafts from the repo** (`repo_scan.py examples`): prompt files and fixtures (JSONL/JSON with input, prompt or chat messages; `*.prompt.md`; prompts/, evals/, fixtures/ folders), with personal data and secrets dropped, template variables flagged, and empty checks for the user to agree.
- **IDE wiring**: `.mcp.json` (Claude Code, Copilot CLI), `.cursor-plugin` and `.codex-plugin` point to it, `gemini-extension.json` declares the server with `${extensionPath}` and `${workspacePath}`.
- **Listing readiness**: MIT license; Anthropic directory fields (`icon`, `documentationUrl`, `supportUrl`, `privacyPolicyUrl`, `termsOfServiceUrl`).
- Refactors for reuse: `parse_config()` (eval), `build_routing()` (routing), `estimate_monthly_cost()` (core).
- New test file `tests/test_mcp.py` drives the server as a subprocess over stdio.

## 1.2.0 (2026-10-13)

- **Personal-data and secrets guard** in eval-models: scans the system prompt and every example before any call. Secrets are always blocked; personal data (Aadhaar with Verhoeff check, PAN, payment cards with Luhn check, email, UPI ID, Indian mobile) blocks the run unless `--allow-personal-data` is passed. Outputs are not saved when personal data is allowed unless `--keep-outputs` is passed. Decisions are recorded in `results.json` and `summary.md`; values are never printed or stored by the guard.
- **Router `pii_policy`** (`block` / `warn` / `off`, default `warn`) via `make_routing.py --pii-policy`.
- **DATA-PROTECTION.md**: data-flow and role analysis per component, DPDP Act obligation mapping, required Cloud Run design, open items for counsel.
- 4 new tests (20 total).

## 1.1.0 (2026-10-13)

- New skill **eval-models**: run your own examples against Claude, Gemini, OpenAI, or any OpenAI-compatible endpoint (including local Ollama/vLLM); reports pass rate, latency, tokens, and cost; cached and reasoning tokens handled; unknown costs never shown as zero; dry run and consent before paid calls.
- New skill **route-models**: cheapest-first routing from eval evidence; standalone router escalates on errors and failed guards; LiteLLM config with error-based fallbacks.
- New skill **size-local-model**: weights plus KV-cache estimate (MHA/GQA), concurrency, KV precision, headroom.
- **find-model**: host-neutral wording (works in IDEs and chat clients), coding-subtask guidance, read-only repo signals with privacy rules.
- Packaging for Claude Code, Codex, Cursor, Gemini CLI, and Copilot CLI from one repository.
- Test suite with a local mock of the three provider APIs.

## 1.0.3

- Preparation release with the find-model skill.
