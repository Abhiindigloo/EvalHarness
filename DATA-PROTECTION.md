# Data protection and DPDP Act 2023

How Model Finder handles personal data, mapped to India's Digital Personal Data Protection Act 2023 (DPDPA) and DPDP Rules 2025.

> This is an engineering record, not legal advice. Have counsel confirm the role analysis, notices, and open items below before launch. Last reviewed: 16 October 2026 (v1.3.5).

## Regulatory status

- DPDP Rules 2025 were notified on 13–14 November 2025 with a phased rollout.
- The core obligations (notice and consent, security safeguards, breach reporting, children's data, retention) were scheduled for 13 May 2027.
- In early 2026 MeitY consulted on shortening this to 12 months (13 November 2026). **Check whether that change has been notified.** Until confirmed, this project is built to meet the obligations now.
- Penalties reach up to ₹250 crore per breach of obligations.

## Who is responsible for what

| Component | Where data goes | Indigloo's role | Personal data Indigloo receives |
|---|---|---|---|
| Plugin skills (find-model, eval-models, route-models, size-local-model) | Runs on the user's machine. Inputs go only to model providers the user configures. | Software publisher, not a Data Fiduciary for user data. The user's organisation decides purpose and means. | None |
| Local MCP server (`mcp/server.py`, v1.3.0) | Runs on the user's machine; no network connections. Tool results go to the user's own AI app (and so to that app's model provider) | Software publisher, not a Data Fiduciary | None |
| Repository and issues (GitHub) | Code download, plus public issues and discussions | Data Fiduciary only for what users choose to post; GitHub acts under its own terms | Whatever a user posts publicly (for example a GitHub username) |
| Planned Cloud Run service | Indigloo's Google Cloud project | Data Fiduciary; Google acts as Data Processor | Request metadata (IP address, user agent) unless minimised; demo inputs if a demo is offered |

**Consequence:** the plugin is designed so Indigloo never receives users' data. For eval and routing, the user's organisation is the Data Fiduciary. The plugin's job is to make it hard to process personal data by accident, and easy for that organisation to meet its own obligations.

## Built-in controls (v1.2.0, extended in v1.3.0)

### Local MCP server (v1.3.0)
- No network access, no key access, no file writes; nothing is sent to Indigloo.
- `modelfinder_audit_models` returns model IDs and file:line locations only, never line content, and skips secret-like files.
- `modelfinder_draft_eval_examples` returns prompt text from the user's own repository to the user's own AI app. Candidates with detected personal data or secrets are dropped and reported only as categories and counts. Because the AI app's provider receives these drafts, prompt files containing personal data the detector cannot see (names, addresses, free text) should be kept out of prompt folders or redacted.
- Repository tools are confined to the workspace and refuse a filesystem root or home directory.

### Data minimisation by default
- **eval-models** scans everything that would be sent (system prompt and every example) before any call.
  - **Secrets** (API keys, private keys): always blocked, no override.
  - **Personal data**: blocked by default. Running requires `--allow-personal-data`, an explicit, recorded decision.
  - When personal data is allowed, model outputs are **not saved** unless `--keep-outputs` is also passed.
  - `results.json` records a `data_protection` block: categories detected, whether they were allowed, whether outputs were saved.
  - `summary.md` has a **Data protection** section that prompts recording the lawful basis and deleting results when no longer needed.
- **route-models** writes `pii_policy` into `routing.json`:
  - `block`: a prompt with detected personal data or secrets is never sent; the router returns a refusal.
  - `warn` (default): sent, and the categories found are returned to the calling app for logging or review.
  - `off`: no check (for apps that already hold consent and their own controls).

### What the detector covers
Aadhaar (with Verhoeff checksum), PAN, payment cards (with Luhn check), email addresses, UPI IDs, Indian mobile numbers, and common secret formats (Anthropic, OpenAI, AWS, Google, GitHub, Slack keys, PEM private keys).

It reports **categories and counts only**; matched values never appear in console output, results, or summaries (verified by tests).

**Limits:** pattern matching cannot detect names, postal addresses, health details, or other free-text personal data, and may produce false positives. It is a safeguard, not a substitute for using redacted or synthetic examples.

### Security safeguards
- Keys only from environment variables, never stored, printed, or included in errors.
- HTTPS only (loopback excepted); redirects refused; size caps on all inputs and responses.
- No third-party dependencies.
- No telemetry: the plugin sends nothing to Indigloo.

## DPDP obligations: what applies where

| Obligation (DPDPA / Rules) | Plugin | Repository and issues | Cloud Run service (planned) |
|---|---|---|---|
| Notice before collection (s.5, Rule 3) | N/A to Indigloo; users' orgs give their own notices | PRIVACY.md in the repository | **Required** before launch |
| Consent / legitimate use (s.4, 6, 7) | User's org decides; guard forces an explicit choice | N/A | **Required** for any demo input |
| Purpose limitation and minimisation | Guard blocks by default | Use posts only to answer them; SUPPORT.md asks users not to post personal data | No accounts, no stored inputs, no prompt logging |
| Reasonable security safeguards (s.8(5), Rule 6) | Built in (see above) | Repository access controls; private vulnerability reporting | See Cloud Run controls below |
| Breach notification: affected people without delay, Board within 72 hours (s.8(6), Rule 7) | N/A | N/A | Needed: incident runbook |
| Erasure when purpose is served (s.8(7), Rule 8) | Outputs off by default when personal data allowed | Edit or delete issue content on request where GitHub allows | Short log retention (see below) |
| Grievance redressal and contact (s.8(10), s.13) | — | SUPPORT.md and PRIVACY.md | Same contact |
| Children's data: verifiable parental consent (s.9) | — | — | Service intended for adults; collect no personal data |
| Processor contracts (s.8(2)) | — | GitHub terms | Google Cloud data processing terms |
| Cross-border transfer (s.16) | User's org; transfers allowed unless a country is restricted by notification | — | Prefer `asia-south1` (Mumbai) region |

## Cloud Run service: required design (before any launch)

1. **No personal data by design.** No accounts, no stored inputs, no cookies. Stateless tools only (sizing, cost maths, config validation, routing generation).
2. **Run the same guard server-side.** Reject requests containing detected personal data or secrets with a clear error; never log the request body.
3. **Logging.** Do not log request bodies or prompts. Keep access/security logs only as long as needed for security and legal requirements. Counsel to confirm the minimum retention required under the Rules, then set a log bucket retention to match.
4. **Region.** Deploy in `asia-south1` (Mumbai); keep any model calls on the same region where available.
5. **Abuse and cost controls.** Max instances, request rate limits, request size limits, budget alerts.
6. **Identity and secrets.** Service account with least privilege; no API keys in code; Secret Manager for anything required.
7. **Transport and headers.** HTTPS only, HSTS, strict CSP, `X-Content-Type-Options`, `frame-ancestors 'none'`.
8. **Notice.** Privacy notice in plain language (English and Hindi recommended), stating what is processed, why, retention, rights, and how to complain to Indigloo and the Data Protection Board.
9. **Incident response.** Named owner, a 72-hour Board notification runbook, and a template for informing affected people.

## Open items for counsel

- Confirm whether the 12-month timeline compression has been notified, and the current effective date for core obligations.
- Confirm Indigloo is not a Data Fiduciary for plugin usage, given it never receives user data.
- Confirm the minimum log retention required under the Rules for the Cloud Run service.
- Confirm the grievance-response timeline to publish.
- Approve PRIVACY.md and TERMS.md (linked from every marketplace listing) and the future Cloud Run notice.
- Decide whether to add Hindi (and other Eighth Schedule language) notices.
- Map these controls into Indigloo's existing ISO/IEC 27001:2022 ISMS (risk register, supplier controls for GitHub and Google Cloud, incident procedure).
