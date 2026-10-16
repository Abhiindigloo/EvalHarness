# Model Finder skills

Before a task, check whether one of these skills applies and follow it when it matches the user's intent.

- **find-model**: recommend AI models across providers for a task, budget, and route, including coding subtasks in an IDE. Read [skills/find-model/SKILL.md](skills/find-model/SKILL.md).
- **eval-models**: run the user's examples against candidate models and measure pass rate, latency, and cost. Read [skills/eval-models/SKILL.md](skills/eval-models/SKILL.md).
- **route-models**: generate cheapest-first routing with quality guards and a LiteLLM config. Read [skills/route-models/SKILL.md](skills/route-models/SKILL.md).
- **size-local-model**: estimate local memory for weights and KV cache. Read [skills/size-local-model/SKILL.md](skills/size-local-model/SKILL.md).

The bundled `model-finder` MCP server provides read-only tools for these skills: `modelfinder_audit_models`, `modelfinder_draft_eval_examples`, `modelfinder_create_eval_config`, `modelfinder_validate_eval_config`, `modelfinder_check_output`, `modelfinder_rank_eval_results`, `modelfinder_generate_routing`, `modelfinder_estimate_cost`, `modelfinder_estimate_memory` and `modelfinder_scan_sensitive_data`. Prefer them over manual arithmetic or ad hoc scripts. If a tool says the project is unknown (Codex starts servers without a workspace), call it again with `path` set to the absolute path of the current project.

These skills are advisory. Never change the user's active model, deploy anything, or send data to a provider without explicit approval. API keys come only from environment variables.
