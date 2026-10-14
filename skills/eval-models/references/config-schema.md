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

- `results.json` (`schema: model-finder-eval/1`): settings, candidates (env var names only), per-candidate summary, recommendation, and per-call records with tokens, cost, latency, failed checks, errors, and output previews (first 4,000 chars unless `--no-outputs`).
- `summary.md`: table, result, caveats, and sample failures.
