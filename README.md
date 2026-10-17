# Model Finder

Find the cheapest AI model that passes your own tests, and keep it that way. Published by Indigloo.

| Skill | What it does |
|---|---|
| `find-model` | Recommends models across Claude, Gemini, OpenAI, cloud, and local options for your task, budget, and route, including coding subtasks in an IDE. |
| `eval-models` | Runs your examples against shortlisted models and measures pass rate, latency, and billed cost with your own keys. |
| `route-models` | Builds a cheapest-first routing setup: a standalone router with quality guards plus a LiteLLM config. |
| `size-local-model` | Estimates memory for weights and KV cache and compares it with your hardware. |

The plugin also ships a **local MCP server** (`mcp/server.py`) with 10 read-only tools, so the same features work as tools in every supported IDE:

| MCP tool | What it does |
|---|---|
| `modelfinder_audit_models` | Lists AI model IDs and SDKs in your repo with file:line locations, routes and hard-coded IDs |
| `modelfinder_draft_eval_examples` | Drafts eval examples from prompt files and fixtures, dropping anything with personal data or secrets |
| `modelfinder_create_eval_config` / `modelfinder_validate_eval_config` | Builds and checks an eval config: call count, env var names, unpriced models, guard verdict |
| `modelfinder_check_output` | Tests a reply against eval checks or routing guards |
| `modelfinder_rank_eval_results` | Ranks results by cost per passing answer, with the cost/reliability cascade |
| `modelfinder_generate_routing` | Returns routing.json and a LiteLLM config from eval results |
| `modelfinder_estimate_cost` | Monthly token cost and cost per accepted result |
| `modelfinder_estimate_memory` | Local memory for weights and KV cache |
| `modelfinder_scan_sensitive_data` | Personal-data and secrets scan (categories and counts only) |

Every tool returns a readable markdown summary by default and the full result as structured JSON (`response_format: "json"` puts the JSON in the text too). Large results are paginated (`limit`, `offset`, `has_more`, `next_offset`), `modelfinder_audit_models` can filter by provider family or hard-coded IDs, and unknown arguments are rejected with the list of valid ones.

The server never opens a network connection, never reads API keys and never writes files. Only `eval_models.py` calls model providers, with your keys, when you run it.

Advisory only: nothing is deployed, your active model is never changed, and data goes only to providers you configure and approve. Personal data and secrets are blocked before sending by default; see [DATA-PROTECTION.md](DATA-PROTECTION.md) for how this maps to India's DPDP Act. Scripts use the Python 3.9+ standard library; there is nothing to `pip install`.

Support: [SUPPORT.md](SUPPORT.md) · Privacy: [PRIVACY.md](PRIVACY.md) · Terms: [TERMS.md](TERMS.md)

## Install

Requires Python 3.9+ on your PATH as `python3` (see Windows note below). Nothing to `pip install`.

| Client | Command | Skills | MCP tools |
|---|---|---|---|
| Claude Code | `/plugin marketplace add Abhiindigloo/EvalHarness` then `/plugin install model-finder@model-finder` | ✅ | ✅ via `mcp/plugin-mcp.json` |
| Cursor | In Agent chat: `/add-plugin https://github.com/Abhiindigloo/EvalHarness` | ✅ | ✅ via `.cursor-plugin/plugin.json` → `mcp/plugin-mcp.json` |
| Gemini CLI | `gemini extensions install https://github.com/Abhiindigloo/EvalHarness` | ✅ | ✅ via `gemini-extension.json` |
| OpenAI Codex CLI | `codex plugin marketplace add Abhiindigloo/EvalHarness` then `codex plugin add model-finder@model-finder` | ✅ | ✅ via `mcp.json` (Agent Plugins format). Codex gives the server no workspace, so the agent passes the project path |
| GitHub Copilot CLI | `copilot plugin marketplace add Abhiindigloo/EvalHarness` then `copilot plugin install model-finder@model-finder` | ✅ | ✅ via `mcp.json` |
| VS Code, JetBrains, Windsurf, other MCP clients | Add the server to the client's MCP settings (below) | — | ✅ |
| Other Agent Skills clients | Copy `skills/<name>/` into the client's skills directory | ✅ | — |

### Manual MCP setup (VS Code, Cursor, JetBrains, Windsurf, others)

Clone the repo once, then point your IDE at `mcp/server.py`. Replace `/absolute/path/to/EvalHarness`.

**VS Code** (`.vscode/mcp.json` in your project; note the top-level key is `servers`):

```json
{
  "servers": {
    "model-finder": {
      "type": "stdio",
      "command": "python3",
      "args": ["/absolute/path/to/EvalHarness/mcp/server.py"],
      "env": { "MODEL_FINDER_ROOT": "${workspaceFolder}" }
    }
  }
}
```

**Cursor** (`.cursor/mcp.json` in your project, or `~/.cursor/mcp.json`):

```json
{
  "mcpServers": {
    "model-finder": {
      "command": "python3",
      "args": ["/absolute/path/to/EvalHarness/mcp/server.py"],
      "env": { "MODEL_FINDER_ROOT": "${workspaceFolder}" }
    }
  }
}
```

**Other clients** (JetBrains AI Assistant, Windsurf, Claude Desktop and most others use `mcpServers`). If the client has no workspace variable, write the project path:

```json
{
  "mcpServers": {
    "model-finder": {
      "command": "python3",
      "args": ["/absolute/path/to/EvalHarness/mcp/server.py"],
      "env": { "MODEL_FINDER_ROOT": "/absolute/path/to/your/project" }
    }
  }
}
```

Gemini CLI only starts extension MCP servers in folders you have trusted; it asks the first time you open a project.

Repository tools read only inside the workspace: the roots your client shares over MCP, else `MODEL_FINDER_ROOT`, else the server's working directory. A filesystem root or home directory is refused.

### Windows

If `python3` is not on your PATH, the MCP server will not start. Install Python from python.org (tick "Add python.exe to PATH") and either create a `python3` alias or use the manual setup above with `"command": "py"` and `"args": ["-3", "C:/path/to/EvalHarness/mcp/server.py"]`.

## Quick start: prove a cheaper model works

In your IDE, ask: "Audit which AI models this repo uses, then draft evals from our prompts and test whether a cheaper model passes." The assistant uses the MCP tools to audit and draft, agrees checks with you, and asks before the paid run.

From a terminal:

```bash
cp skills/eval-models/assets/example-config.json my-eval.json   # fill in verified model IDs and prices
export ANTHROPIC_API_KEY=... GEMINI_API_KEY=... OPENAI_API_KEY=...
python3 skills/eval-models/scripts/repo_scan.py audit .            # what the repo uses
python3 skills/eval-models/scripts/repo_scan.py examples .         # draft examples from prompt files
python3 skills/eval-models/scripts/eval_models.py my-eval.json --dry-run
python3 skills/eval-models/scripts/eval_models.py my-eval.json --out results
python3 skills/route-models/scripts/make_routing.py --results results/results.json --guards guards.json --out routing
python3 routing/router.py routing/routing.json "your prompt"
```

Or just ask your assistant: "Test whether a cheaper model passes on my examples."

## Size a local model

```bash
python3 skills/size-local-model/scripts/estimate_memory.py --params-b 8.03 --bits 16 \
  --layers 32 --kv-heads 8 --head-dim 128 --context 8192 --available-gib 24
```

## Tests

```bash
python3 -m unittest discover -s tests -v
```

End-to-end tests run against a local mock of the OpenAI-compatible, Anthropic, and Gemini APIs, and drive the MCP server over stdio; no key or network access is needed.

## Repository layout

```
skills/                      shared Agent Skills (single source of truth)
mcp/server.py                local MCP server (stdio, standard library only)
mcp/plugin-mcp.json          MCP launch config for Claude Code and Cursor (kept out of the repo root so it never
                             loads as a project MCP config when you work inside this repo)
mcp.json                     Agent Plugins MCP launch config (Codex, Copilot CLI); uses ${PLUGIN_ROOT}
.claude-plugin/              Claude Code (and Copilot CLI) plugin + marketplace manifests
.codex-plugin/               Codex plugin manifest
.agents/plugins/             Codex repository marketplace
.cursor-plugin/              Cursor plugin + marketplace manifests
gemini-extension.json        Gemini CLI extension (context: GEMINI.md)
plugin.json                  Agent Plugins manifest with OpenAI listing metadata
AGENTS.md, GEMINI.md         skill index for agents that read root instructions
PRIVACY.md, TERMS.md, SUPPORT.md  pages the marketplace listings link to
```

`skills/eval-models/scripts/mf_core.py` is duplicated in `skills/route-models/scripts/` so each skill works on its own. The test suite fails if the copies differ.

## Security and license

See [SECURITY.md](SECURITY.md) and [DATA-PROTECTION.md](DATA-PROTECTION.md). Licensed under the [MIT License](LICENSE).
