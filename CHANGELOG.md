# Changelog

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
