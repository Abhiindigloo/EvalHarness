# Privacy Policy

**Model Finder** — published by Indigloo Softwares Private Limited ("Indigloo", "we"), a company incorporated in India.
Effective date: 17 October 2026. Applies to version 1.3.5 and later.

## Summary

- Model Finder runs entirely on your own computer. **Indigloo does not receive, store or see any data you use with it.**
- It has no accounts, no sign-in, no telemetry, no analytics, no cookies and no advertising.
- The local MCP server makes **no network connections**, reads no API keys, writes no files and never logs what you send it.
- Data reaches a model provider only when **you** run the eval script or the router it generates, using **your** API keys, and only for providers **you** configure.

## 1. Scope

This policy covers the Model Finder software in this repository wherever it is installed: the four Agent Skills (`find-model`, `eval-models`, `route-models`, `size-local-model`), the local MCP server (`mcp/server.py`, also distributed on PyPI as `model-finder-mcp`), and the command-line scripts. It also covers how Indigloo handles what you send us through the project's GitHub repository.

It does not cover the AI assistant or IDE you use Model Finder in (for example Claude, ChatGPT, Codex, Cursor, Gemini CLI, GitHub Copilot or VS Code), the model providers you choose to call, or the marketplaces and package registries you install it from. Each of those has its own privacy terms.

## 2. What the software processes, and where it goes

| Component | What it processes | Where the data goes | Retained by Indigloo |
|---|---|---|---|
| Skills | Your instructions and the files your assistant reads | To your AI assistant and its provider, under that assistant's terms | Nothing |
| Local MCP server | Repository files inside the project you have open, and the tool arguments your assistant sends | Tool results go back to your AI assistant only. No network connection is made | Nothing |
| Eval script (`eval_models.py`) | The prompts and examples in your eval config | Only to the model providers you list, with your own API keys, after you start the run | Nothing |
| Generated router (`router.py`) | Prompts your application sends it | Only to the models in your routing file | Nothing |
| Cost and memory calculators | Numbers you provide | Nowhere; calculated locally | Nothing |

## 3. Data minimisation in the MCP server

The MCP server only reads what a tool needs to do its job:

- Repository tools read only inside the workspace your client shares (or the folder you configure) and refuse a filesystem root or home folder.
- They skip secret-like files (`.env`, keys, certificates, credential and token files), dependency and build folders, and symbolic links.
- `modelfinder_audit_models` returns model IDs, file names and line numbers, **never line content**.
- `modelfinder_draft_eval_examples` drops any example in which personal data or secrets are detected, and reports only the category and count.
- `modelfinder_scan_sensitive_data` reports categories and counts, **never the values it found**.
- The server does not request, read or store your conversation, chat history, or your assistant's memory, and it does not log the tool arguments it receives (an unexpected internal error writes only the error type and code location to your host's local log).

## 4. Personal data and secrets safeguards

- Eval runs are **blocked** when examples contain detected personal data (Aadhaar, PAN, payment cards, email addresses, UPI IDs, Indian mobile numbers) unless you explicitly allow it with `--allow-personal-data`. When you allow it, model replies are not saved unless you also ask for them.
- API keys and private keys are **never sent** to providers, with no override.
- API keys are read only from environment variables and are never printed, written to disk or included in error messages.
- The router can block, warn about or ignore prompts containing personal data (`pii_policy`).

Pattern matching cannot detect names, postal addresses, health information or other free-text personal details. Use redacted or synthetic examples.

## 5. Files the software writes on your computer

Only when you run a command that writes output: the eval script writes `results.json` and `summary.md` to the folder you choose, and the routing script writes `routing.json`, `router.py`, `mf_core.py`, `litellm.config.yaml` and `ROUTING.md` to the folder you choose. These stay on your computer. You control their retention and can delete them at any time.

## 6. What Indigloo collects

**Through the software: nothing.** Indigloo does not run a server, API or hosted service for Model Finder.

**Through GitHub:** if you open an issue, discussion or pull request, or report a vulnerability privately, Indigloo receives what you choose to post, together with your GitHub username. We use it only to answer you and improve the software. Public posts are visible to everyone and are handled by GitHub under the [GitHub Privacy Statement](https://docs.github.com/en/site-policy/privacy-policies/github-general-privacy-statement). Please do not post personal data, API keys or confidential code.

**Through package registries and marketplaces:** PyPI, the MCP Registry and AI assistant marketplaces may record downloads or installs under their own policies. Indigloo does not receive personal data from them.

We do not sell, rent or share personal data, and we do not use it for advertising or for training AI models.

## 7. Third parties you choose

When you configure a model provider (for example Anthropic, Google, OpenAI, or an OpenAI-compatible or local endpoint), the eval script and router send your prompts to that provider using your account. That provider's terms and privacy policy apply, including its rules on retention, training use and data location. Check them before sending real data.

## 8. Your organisation's role

When you use Model Finder to send data to model providers, **your organisation** decides what is sent and why. Under India's Digital Personal Data Protection Act 2023 and similar laws, your organisation is responsible for its legal basis, notices and provider agreements. [DATA-PROTECTION.md](DATA-PROTECTION.md) shows how the built-in controls support those obligations.

## 9. Security

The software uses only the Python standard library, so it has no third-party code to compromise. It requires HTTPS for provider calls (loopback excepted), refuses redirects, caps input sizes, and is covered by automated tests. Releases are built and published from GitHub Actions with pinned dependencies. See [SECURITY.md](SECURITY.md).

## 10. Children

Model Finder is a developer tool intended for adults. It is not directed at children under 18, and Indigloo does not knowingly collect children's personal data.

## 11. Your rights

Because Indigloo holds no personal data from your use of the software, there is nothing for us to access, correct or delete on that basis. For anything you have posted on GitHub, you can edit or delete it yourself where GitHub allows, or ask us to help. Under the DPDP Act you may also raise a grievance with us and, if unresolved, with the Data Protection Board of India.

## 12. Changes

We will update this policy when the software's data handling changes, and record each change in this file's history on GitHub and in [CHANGELOG.md](CHANGELOG.md). The effective date at the top shows the current version.

## 13. Contact

- Privacy questions and grievances: open an issue at https://github.com/Abhiindigloo/EvalHarness/issues asking for a private channel, without including personal details.
- Security or confidential matters: use the repository's private vulnerability reporting (Security tab → "Report a vulnerability").
- More detail: [SUPPORT.md](SUPPORT.md).
