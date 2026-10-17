# Terms of Use

**Model Finder** — published by Indigloo Softwares Private Limited ("Indigloo", "we"), a company incorporated in India.
Effective date: 17 October 2026.

By installing or using Model Finder you agree to these terms. If you use it on behalf of an organisation, you agree for that organisation.

## 1. The software and its license

Model Finder is open-source software licensed under the [MIT License](LICENSE). The MIT License governs your rights to use, copy, modify and distribute the code. These terms add how the software should be used and what Indigloo is and is not responsible for. If these terms and the MIT License conflict about your rights in the code, the MIT License prevails.

## 2. What Model Finder does

Model Finder helps you choose AI models. It recommends candidates, audits the models a repository uses, drafts and runs evaluations with your own keys, generates routing configurations, and estimates cost and memory. It is advisory:

- It never changes your active model, deploys anything or starts a service.
- The local MCP server makes no network connections and writes no files.
- Indigloo does not operate a hosted service, accounts or paid plans for Model Finder. The software is free.

## 3. Outputs are estimates, not guarantees

- Recommendations, prices, model IDs and availability can be wrong or out of date. Verify them on each provider's official pages before relying on them.
- Evaluation results reflect only your examples and checks. A small sample is a smoke test, not proof of quality.
- Memory estimates do not guarantee that a model fits or runs well on your hardware.
- Generated routing and LiteLLM configurations must be reviewed and tested by you before use.

## 4. Your responsibilities

- **Providers and costs.** You choose which providers to call. Eval runs and routing use your own API keys and accounts, and you pay those providers' charges.
- **Data.** You are responsible for the data you send to providers, for having the right to send it, and for complying with the laws, contracts and provider terms that apply to you, including data protection law.
- **Keys.** Keep API keys in environment variables or a secret manager. Never put them in configs, prompts, issues or pull requests.
- **Acceptable use.** Do not use Model Finder to break the law, to infringe others' rights, to violate the usage policies of the AI assistant or model providers you use, or to attempt to bypass their safety measures.

## 5. Third-party services

Model Finder works with AI assistants, IDEs, model providers, marketplaces and package registries that Indigloo does not control. Their terms and privacy policies apply to your use of them. Indigloo is not responsible for their services, availability, pricing or outputs.

## 6. No warranty

The software is provided "as is" and "as available", without warranty of any kind, express or implied, including fitness for a particular purpose, accuracy and non-infringement, as stated in the MIT License.

## 7. Limitation of liability

To the fullest extent permitted by law, Indigloo and the contributors are not liable for any indirect, incidental, special, consequential or punitive damages, or for any loss of profits, revenue, data or provider charges, arising from your use of the software or its outputs. Because the software is free, Indigloo's total liability for any claim relating to it is limited to zero rupees, except where the law does not allow that limit.

## 8. Trademarks

"Model Finder" and "Indigloo" are names used by Indigloo. Claude, Gemini, GPT, Codex, Cursor, Copilot and other product and model names belong to their owners. They are used only to identify those products and do not imply endorsement or partnership.

## 9. Changes

We may update these terms. Changes are recorded in this file's history on GitHub, and the effective date above shows the current version. Continuing to use a newer version of the software means you accept the terms that come with it.

## 10. Governing law

These terms are governed by the laws of India. Courts in Mumbai, Maharashtra have jurisdiction, subject to any mandatory rights you have under the law where you live.

## 11. Contact

See [SUPPORT.md](SUPPORT.md). For security issues, see [SECURITY.md](SECURITY.md).
