# Eval config schema (model-finder eval)

A JSON object. Unknown top-level fields are ignored.

| Field | Required | Rules |
|---|---|---|
| `task` | no | Short description, up to 2,000 chars. |
| `settings.max_output_tokens` | yes | Integer 1–64,000. Applied to every candidate. |
| `settings.timeout_s` | no | 1–600, default 60. |
| `settings.temperature` | no | 0–2. Omit for models that reject it (some reasoning models do). |
| `settings.system` | no | System prompt, up to 50,000 chars. |
| `pass_threshold` | no | 0–1, default 1.0. Fraction of calls that must pass every check. |
| `repeats` | no | 1–10, default 1. Use 3+ for noisy tasks. |
| `candidates` | yes | 1–10 objects, below. |
| `examples` | yes | 1–500 objects, below. |

## Candidate

| Field | Rules |
|---|---|
| `id` | Unique label: letters, digits, `.`, `_`, `-` (max 64). |
| `provider` | `anthropic`, `openai`, `gemini`, or `openai_compatible`. |
| `model` | Exact provider model ID, verified from official docs. |
| `api_key_env` | Name of the environment variable holding the key (UPPER_SNAKE). Required except for keyless `openai_compatible` local servers. |
| `base_url` | Optional for anthropic/openai/gemini (defaults to the official API); required for `openai_compatible`. HTTPS only, except `http://localhost` or loopback IPs. No credentials, query strings, or fragments. |
| `price_per_million` | `null`, or `{"input", "output", "cached_input"?, "source", "checked"}` in USD per million tokens. `source` and `checked` are required. |

Fields named `api_key`, `key`, `token`, `secret`, or `authorization` are rejected so keys never live in the file.

### Provider endpoints used

- `anthropic`: `POST {base_url}/v1/messages` with `x-api-key` and `anthropic-version: 2023-06-01`.
- `openai`: `POST {base_url}/v1/chat/completions` with `max_completion_tokens`.
- `gemini`: `POST {base_url}/v1beta/models/{model}:generateContent` with `x-goog-api-key`.
- `openai_compatible`: `POST {base_url}/v1/chat/completions` with `max_tokens` (OpenRouter, Ollama, vLLM, LM Studio, gateways).

Cloud-hosted routes (Bedrock, Vertex AI, Azure OpenAI) are reached through an OpenAI-compatible gateway or proxy; verify that gateway's terms separately.

### Token accounting

- Cached input is separated from uncached input (OpenAI `cached_tokens`, Anthropic `cache_read_input_tokens`, Gemini `cachedContentTokenCount`) and billed at `cached_input` if given, otherwise at the full input price, with a note.
- Gemini thinking tokens and OpenAI reasoning tokens are counted as output, as billed.
- If a provider omits usage, cost is reported as unknown.

## Example

| Field | Rules |
|---|---|
| `id` | Unique, up to 64 chars (defaults to `ex-N`). |
| `input` | The user prompt, up to 200,000 chars. Redacted or synthetic. |
| `checks` | 1–50 checks, all must pass. |
| `tags` | Optional groups for per-tag results, e.g. `["extraction", "hindi"]`. Lowercase letters, digits and `-`, up to 32 chars each, at most 8 per example; duplicates are removed and tags are sorted. `untagged` is reserved for examples without tags. |

### Check types

| `type` | Fields | Passes when |
|---|---|---|
| `contains` | `value`, `ignore_case`? | reply includes `value` |
| `not_contains` | `value`, `ignore_case`? | reply does not include `value` |
| `exact` | `value`, `ignore_case`? | trimmed reply equals trimmed `value` |
| `regex` | `pattern` (≤500 chars) | pattern found (first 100,000 chars searched) |
| `json_keys` | `keys` | reply parses as a JSON object (one fenced block allowed) containing every key |
| `max_chars` | `value` | reply length ≤ `value` |

## Outputs

- `results.json` (`schema: model-finder-eval/2`, `schema_version: 2`): settings, configured `repeats`, the `examples` list (id, tags, fingerprint), candidates (env var names only), per-candidate summary with `evidence`, recommendation, and per-call records with tokens, cost, latency, failed checks, errors, and output previews (first 4,000 chars unless `--no-outputs`).
- `summary.md`: table, coverage and evidence (with a by-tag table when examples are tagged), result, caveats, and sample failures.

Version 1 results files (`model-finder-eval/1`) still load in the ranking and routing tools; they have no example list, so tags are empty and fingerprints unknown.

### Example fingerprint

`sha256:` + SHA-256 of the example's normalised input (Unicode NFC, LF line endings, surrounding whitespace trimmed), its validated checks (order does not matter) and its sorted tags. Any change to the input, checks or tags gives a new fingerprint, so two runs are compared example by example only where fingerprints match.

### Evidence per candidate (`summary[].evidence`)

| Field | Meaning |
|---|---|
| `unique_examples`, `configured_repeats`, `scheduled_attempts`, `completed_attempts`, `incomplete_attempts` | Examples vs attempts, e.g. "4 unique examples, 2 configured repeats, 7 completed attempts". |
| `errored_attempts` | Completed attempts that errored; they count as failures. |
| `missing_measurements` | Non-errored attempts with no `cost`, `usage` or `latency`. |
| `per_example` | Status per example id: `pass` (every completed attempt passed), `fail` (every completed attempt failed), `mixed`, or `no_data` (no completed attempts). `pass` describes observed attempts only. |
| `statuses`, `example_pass_rate` | Counts of each status; passing examples ÷ unique examples. |
| `by_tag` | The same counts per tag, plus `untagged`. An example with several tags counts in each group, so groups can overlap; overall figures always come from unique examples. |

`pass_rate` and `cost_per_pass_usd` are unchanged and attempt-based (`cost_per_pass_basis: "passing attempts"`).
