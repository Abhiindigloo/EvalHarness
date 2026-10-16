# Privacy notice

**Model Finder** (this repository), published by Indigloo Softwares Private Limited.
Last updated: 16 October 2026. Draft for legal review before marketplace submission.

## In short

Model Finder runs on your own computer. Indigloo does not receive, store or see the data you use with it. The plugin has no accounts, no telemetry and no analytics.

## What runs where

| Part | What it processes | Where data goes |
|---|---|---|
| Skills (`find-model`, `eval-models`, `route-models`, `size-local-model`) | Your instructions and files, through your AI assistant | To your AI assistant's provider, under that assistant's terms |
| Local MCP server (`mcp/server.py`) | Repository files you ask it to scan, inside your open project | Results go back to your AI assistant only. The server opens no network connections |
| Eval script (`eval_models.py`) | The examples and prompts in your eval config | Only to the model providers you configure, using your own API keys, after you start the run |
| Router (`router.py`) | Prompts your application sends it | Only to the models in your routing file |

## What Indigloo collects

Nothing through the software. Indigloo does not operate a server for this plugin.

If you open an issue or discussion on GitHub, what you post is public and is handled by GitHub under the [GitHub Privacy Statement](https://docs.github.com/en/site-policy/privacy-policies/github-general-privacy-statement). Indigloo reads it to answer you. Do not post personal data, API keys or confidential code in issues.

## Personal data protections built in

- Eval runs are blocked when examples contain detected personal data (Aadhaar, PAN, payment cards, email addresses, UPI IDs, Indian mobile numbers) unless you explicitly allow it. When allowed, model replies are not saved unless you ask.
- API keys and private keys are never sent to providers, with no override. Keys are read only from environment variables and never written to disk.
- Repository scans skip secret files such as `.env`, keys and certificates, stay inside your project, and report categories and counts, never matched values.

Pattern matching cannot detect names, addresses or other free-text personal details. Use redacted or synthetic examples.

## Your organisation's responsibilities

When you send data to model providers with this software, your organisation decides what is sent and why, and is responsible for its own legal basis, notices and provider agreements, including under India's Digital Personal Data Protection Act 2023. See [DATA-PROTECTION.md](DATA-PROTECTION.md) for how the controls map to that Act.

## Contact

For privacy questions or complaints, see [SUPPORT.md](SUPPORT.md). To raise something privately, use the repository's private vulnerability reporting or ask in an issue for a private contact channel, without including personal details.

## Changes

Changes to this notice are recorded in this file's history on GitHub.
