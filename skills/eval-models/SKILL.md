---
name: eval-models
description: Run the user's own examples against several AI models (Claude, Gemini, OpenAI, or any OpenAI-compatible endpoint including local Ollama or vLLM) and measure pass rate, latency, and billed cost to find the cheapest model that meets their quality bar. Use whenever the user wants to test, benchmark, evaluate, or prove which model works for their task, asks "is the cheaper model good enough", wants evidence before switching models, or has a shortlist from find-model to validate, even if they don't say "eval". Generates a config, runs a standard-library Python script with the user's keys from environment variables, and writes results.json plus a summary.
metadata:
  author: Indigloo
  homepage: https://abhiindigloo.github.io/modelfinder-website/
---

# Evaluate models on the user's examples

Turn a model recommendation into evidence. The script sends identical prompts to each candidate, applies deterministic checks to every reply, and reports pass rate, latency, tokens, and cost. It uses only the Python 3.9+ standard library.

## Workflow

1. **Agree the candidates.** Use the shortlist from find-model or the user's list. Each needs the exact current model ID and route; verify IDs from official docs. Read references/config-schema.md for the fields and supported providers.

2. **Collect examples.** Ask for 10 to 30 representative inputs, including hard and edge cases. They should be redacted or synthetic. Fewer than 10 examples is a smoke test; say so.

   The script scans the system prompt and every example before any call. Secrets (API keys, private keys) are always blocked. Personal data (Aadhaar, PAN, payment cards, emails, UPI IDs, Indian mobile numbers) blocks the run unless `--allow-personal-data` is passed. Only suggest that flag when the user confirms they have a lawful basis (for example consent) and are permitted to send that data to every candidate provider; under India's DPDP Act the user's organisation is responsible for that decision. When it is used, outputs are not saved unless `--keep-outputs` is added. The detector cannot see names, addresses, or free-text personal details, so still ask for redacted examples.

3. **Define checks with the user.** Checks must reflect what "correct" means for their task: required fields (`json_keys`), required or forbidden content (`contains`, `not_contains`), formats (`regex`), exact answers (`exact`), and length (`max_chars`). Agree the pass threshold before running. Deterministic checks cannot grade open-ended quality such as tone or summary faithfulness; for those, keep outputs and have a human review them. Do not invent a grading score.

4. **Fill prices only from verified sources.** Set `price_per_million` from the provider's official pricing page for that exact route, with `source` (URL) and `checked` (date). If not verified, use `null`; the summary then reports cost as unknown, never as zero.

5. **Write the config** with assets/example-config.json as the template. Keys go in environment variables referenced by `api_key_env`; the script rejects configs that contain key values.

6. **Dry run first.** Run `python3 scripts/eval_models.py config.json --dry-run`. It validates everything, lists missing environment variables, and reports the number of API calls. It makes no network requests.

7. **Get explicit consent before the real run.** State the number of calls, which providers receive the examples, and that the run costs money on the user's accounts. Run only after the user agrees:
   `python3 scripts/eval_models.py config.json --out model-eval-results`
   Use `--no-outputs` if the replies themselves are sensitive.

8. **Report from summary.md.** Lead with the cheapest candidate meeting the threshold, then the table, then caveats (sample size, checks that cannot judge quality, unknown costs, truncated outputs). Quote measured numbers only from results.json or summary.md.

9. **Offer route-models** to build a cheapest-first routing setup from results.json.

## When code cannot run here

If the host cannot execute code or reach the network, give the user the finished config and the exact commands to run locally, and offer to interpret results.json when they share it. Never present predicted results as measured ones.

## Guarantees and limits

- Keys are read from the environment, never printed, and never written to disk. HTTPS is required except for loopback hosts; redirects are refused.
- Retries: up to two on HTTP 429 and 5xx, honoring `Retry-After` (capped at 30 seconds).
- Latency includes network time from the user's machine.
- Cost uses the configured prices and reported token usage, including cached and reasoning tokens where the provider reports them. Batch discounts, tiered pricing, and taxes are not modeled; mention them when relevant.
- The script never changes any default model, deploys anything, or uploads results.
- `results.json` and `summary.md` record what personal data was detected and allowed (categories and counts only, never values). See DATA-PROTECTION.md at the repository root.
