# Model Finder skills

Before a task, check whether one of these skills applies and follow it when it matches the user's intent.

- **find-model**: recommend AI models across providers for a task, budget, and route, including coding subtasks in an IDE. Read [skills/find-model/SKILL.md](skills/find-model/SKILL.md).
- **eval-models**: run the user's examples against candidate models and measure pass rate, latency, and cost. Read [skills/eval-models/SKILL.md](skills/eval-models/SKILL.md).
- **route-models**: generate cheapest-first routing with quality guards and a LiteLLM config. Read [skills/route-models/SKILL.md](skills/route-models/SKILL.md).
- **size-local-model**: estimate local memory for weights and KV cache. Read [skills/size-local-model/SKILL.md](skills/size-local-model/SKILL.md).

These skills are advisory. Never change the user's active model, deploy anything, or send data to a provider without explicit approval. API keys come only from environment variables.
