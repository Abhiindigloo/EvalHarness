# Choosing models for coding work

## Split the work by subtask

One model rarely fits every coding subtask. Recommend per subtask when the user's tools allow it:

- **Planning, architecture, hard debugging**: favor strong reasoning and long-context reliability; volume is low, so price matters less.
- **Routine edits, boilerplate, test scaffolding, docs**: a cheaper, faster model often passes; confirm with the repo's tests.
- **Code review**: favor careful, high-recall models. A reviewer from a different family than the author model can catch different mistakes; present this as a hypothesis to test, not a fact.
- **Autocomplete and inline suggestions**: latency dominates; small, fast models are usually the right class.
- **Agentic loops (multi-step edits with tools)**: judge tool-use reliability, instruction following across many turns, and total cost per completed task, including retries and extra turns.

## Judge by the repository, not by leaderboards

Acceptance for coding work is concrete: the change builds, the required tests pass, linters pass, and a reviewer accepts it. Prefer that evidence over public benchmarks. When the user wants proof, use eval-models with prompts drawn from real, redacted tasks and checks on the output format; for full build-and-test acceptance, explain that each candidate's patch must be applied and tested in the user's environment, and do not claim results that were not run.

Measure **cost per accepted change**, not cost per token. A cheaper model that needs three attempts can cost more than a stronger model that succeeds once.

## Context needs

Coding agents usually send selected files, diffs, and tool output, not the whole repository. Estimate the typical and largest request, leave headroom for system prompts and tool results, and remember that an advertised context window does not guarantee reliable use of all of it.

## Reading the repository (optional, read-only)

Only when repository context would change the recommendation and the host grants file access:

- Gather coarse signals: language mix by file extension, approximate size, whether a test command exists, and frameworks in manifest files (package.json, pyproject.toml, go.mod, pom.xml).
- Do not open or quote secrets or credentials: skip `.env*`, key and certificate files, credential stores, and anything excluded by `.gitignore`.
- Do not send repository content to any external service. Summarize findings in the conversation only.

## What this skill can and cannot do in an IDE

- It cannot change the IDE's active model, billing plan, or settings. Tell the user where the choice is made (the tool's model picker or configuration) and let them switch.
- IDE built-in model lists, plan quotas, and data-handling terms differ from direct API access. Verify the route the user actually uses.
- Code sent to a model is shared with that provider under the route's terms. For regulated or confidential code, verify retention, training-use, and regional terms on that specific route before recommending it.
