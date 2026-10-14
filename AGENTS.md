# Model Finder skills

Before a task, check whether one of these skills applies and follow it when it matches the user's intent.

- **find-model**: recommend AI models across providers for a task, budget, and route, including coding subtasks in an IDE. Read [skills/find-model/SKILL.md](skills/find-model/SKILL.md).
- **eval-models**: run the user's examples against candidate models and measure pass rate, latency, and cost. Read [skills/eval-models/SKILL.md](skills/eval-models/SKILL.md).
- **route-models**: generate cheapest-first routing with quality guards and a LiteLLM config. Read [skills/route-models/SKILL.md](skills/route-models/SKILL.md).
- **size-local-model**: estimate local memory for weights and KV cache. Read [skills/size-local-model/SKILL.md](skills/size-local-model/SKILL.md).

These skills are advisory. Never change the user's active model, deploy anything, or send data to a provider without explicit approval. API keys come only from environment variables.

## Cursor Cloud specific instructions

- **Stack:** Python 3.9+ only; scripts use the standard library (no `pip install`).
- **Tests:** `python3 -m unittest discover -s tests -v` (includes mock-provider end-to-end tests; no API keys or network).
- **CLI smoke:** `python3 skills/size-local-model/scripts/estimate_memory.py --params-b 8.03 --bits 16 --layers 32 --kv-heads 8 --head-dim 128 --context 8192 --available-gib 24`
- **Live evals:** require provider API keys in the environment and a config with real model IDs (not `example-config.json` placeholders).
