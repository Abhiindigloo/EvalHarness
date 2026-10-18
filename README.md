# modelfinder.indigloo.co

Static landing page for [Model Finder](https://github.com/Abhiindigloo/EvalHarness). This `site` branch is deployed by Cloudflare Pages; it is kept off `main` so the plugin that directories scan stays unchanged.

- No build step: Cloudflare Pages serves this folder as is (build command empty, output directory `/`).
- No analytics, cookies or third-party requests. Fonts are self-hosted (Instrument Serif, Instrument Sans, Geist Mono; SIL OFL, licences in `fonts/`).
- `_headers` sets the security headers and caching.
