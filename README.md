# Model Finder

Choose AI models with evidence, not hype. Published by Indigloo.

| Skill | What it does |
|---|---|
| `find-model` | Recommends models across Claude, Gemini, OpenAI, cloud, and local options for your task, budget, and route, including coding subtasks in an IDE. |
| `eval-models` | Runs your examples against shortlisted models and measures pass rate, latency, and billed cost with your own keys. |
| `route-models` | Builds a cheapest-first routing setup: a standalone router with quality guards plus a LiteLLM config. |
| `size-local-model` | Estimates memory for weights and KV cache and compares it with your hardware. |

Advisory only: nothing is deployed, your active model is never changed, and data goes only to providers you configure and approve. Personal data and secrets are blocked before sending by default; see [DATA-PROTECTION.md](DATA-PROTECTION.md) for how this maps to India's DPDP Act. Scripts use the Python 3.9+ standard library; there is nothing to `pip install`.

Website: https://abhiindigloo.github.io/modelfinder-website/

## Install

| Client | Command |
|---|---|
| Claude Code | `/plugin marketplace add Abhiindigloo/EvalHarness` then `/plugin install model-finder@model-finder` |
| OpenAI Codex CLI | `codex plugin marketplace add Abhiindigloo/EvalHarness` then `codex plugin install model-finder@model-finder` |
| Cursor | In Agent chat: `/add-plugin https://github.com/Abhiindigloo/EvalHarness` |
| Gemini CLI | `gemini extensions install https://github.com/Abhiindigloo/EvalHarness` |
| GitHub Copilot CLI | `copilot plugin marketplace add Abhiindigloo/EvalHarness` |
| Other Agent Skills clients | Copy `skills/<name>/` into the client's skills directory. |

## Quick start: prove a cheaper model works

```bash
cp skills/eval-models/assets/example-config.json my-eval.json   # fill in verified model IDs and prices
export ANTHROPIC_API_KEY=... GEMINI_API_KEY=... OPENAI_API_KEY=...
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

End-to-end tests run against a local mock of the OpenAI-compatible, Anthropic, and Gemini APIs; no key or network access is needed.

## Repository layout

```
skills/                      shared Agent Skills (single source of truth)
.claude-plugin/              Claude Code (and Copilot CLI) plugin + marketplace manifests
.codex-plugin/               Codex plugin manifest
.agents/plugins/             Codex repository marketplace
.cursor-plugin/              Cursor plugin + marketplace manifests
gemini-extension.json        Gemini CLI extension (context: GEMINI.md)
plugin.json                  Agent Plugins manifest with OpenAI listing metadata
AGENTS.md, GEMINI.md         skill index for agents that read root instructions
```

`skills/eval-models/scripts/mf_core.py` is duplicated in `skills/route-models/scripts/` so each skill works on its own. The test suite fails if the copies differ.

## Security

See [SECURITY.md](SECURITY.md).
