# Evaluations

Ten questions that test whether an AI agent can answer realistic questions using **only** the Model Finder MCP
tools, following the MCP builder evaluation method: read-only, independent, single verifiable answers that do
not change.

- `fixture-repo/`: a small helpdesk codebase with models in several services, routes through Bedrock, Vertex AI
  and Groq, an environment-variable default, legacy models, prompt files, and eval fixtures containing **fake**
  personal data and a documentation example key. It is the workspace for every question.
- `model_finder_eval.xml`: the questions and verified answers.
- `run_with_claude_code.py`: runs every question through headless Claude Code with the plugin loaded and built-in
  file, shell and web tools denied, then prints the score.

```bash
python3 evaluations/run_with_claude_code.py
```

## Latest result

10 of 10 correct (Claude Code 2.1.301, 17 October 2026; also 10 of 10 on 2.1.299). Each question took one or two MCP tool calls.

If you change the fixture, recompute the answers with the MCP tools before running, and update this file.
The `.gitignore` excludes `.env` files, so the fixture uses `credentials.json` (kept by a `.gitignore` exception) to exercise secret-file skipping.
