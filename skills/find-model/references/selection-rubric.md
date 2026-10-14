# Task-specific selection rubric

## Hard constraints before ranking

Exclude candidates with unverified or incompatible mandatory modality, context/output capacity, deployment region, license, hardware, required tools/structured output, or data handling requirements. Label unknown constraints as unresolved; do not interpret missing evidence as compliance. Leave headroom for system prompts, retrieved content, tool output and responses. Advertised context length alone does not prove reliable long-context performance.

Compare equivalent product routes. A first-party API, consumer subscription, cloud marketplace deployment, and local runtime can differ in model ID, features, regions, price, terms, retention, and support. Verify the route the user can actually use; do not attribute one route's facts to another.

## Evidence and tradeoffs

Compare quality on representative user tasks, total cost per successful result, end-to-end latency, reliability, and integration effort. Prefer direct task evaluation over unrelated public benchmarks. Official specifications establish supported features, not guaranteed task success. Independent benchmarks may supplement official sources; state dataset, date and relevance when available. Confidence should distinguish verified specifications from tentative task fit.

Possible task measures:
- Coding: required tests pass, correctness, security and maintainability.
- Extraction: field accuracy, schema validity, omission and hallucination rate.
- Research: source validity, factual accuracy, citation support and completeness.
- Writing: adherence to brief, factual fidelity, tone and human acceptance.
- Vision/audio: relevant accuracy on realistic lighting, languages and noise.
- Retrieval/embeddings: recall and precision on the intended corpus; dimension and index cost.
- Image generation: prompt adherence, visual quality, edit consistency and usage rights.

Use user-specified priorities. If a scoring matrix helps, disclose weights, normalize all criteria consistently, mark unknowns, and label subjective ratings. Avoid manufacturing a score from specifications alone.

## Cost calculation

For token-billed APIs with per-million prices:

cost_per_request = (uncached_input_tokens * input_price + cached_input_tokens * cached_input_price + billed_output_tokens * output_price) / 1,000,000 + tool_fees + other_usage_fees

monthly_cost = requests_per_month * expected_cost_per_request

Use the relevant route's billing definitions for reasoning tokens, cache creation/read, audio/image tokens, batch discounts, minimums and tiers. Include retries and fallback calls when applicable. Do not double count cached tokens as uncached. If cache eligibility is unknown, calculate without cache discounts. Show currency, source route and pricing date; currency conversion needs a verified rate/date. Compare cost per accepted task when failure rates differ.

For other billing units use the provider's actual formula. Do not assume all providers meter image, audio, tools, or cached input the same way. For local inference assess memory, quantization, throughput and measured quality as well as hardware rental/purchase, electricity and operations.

## Small evaluation plan

Use 10–30 redacted representative examples when practical, including edge cases. Fix prompts, tools, settings and output limits across compatible candidates. Define the quality acceptance threshold before running. Record pass rate, severity of failures, end-to-end latency and actual billed cost; repeat stochastic or noisy tasks when needed. State sample limitations. Pick the cheapest candidate that passes all mandatory criteria; escalate low-confidence or failed outputs to a stronger candidate only if the routing can detect those failures reliably.
