#!/usr/bin/env python3
"""Model Finder MCP server (local, stdio, Python standard library only).

Exposes the Model Finder calculators, checkers and repository scanners as MCP
tools. It never opens a network connection, never reads API keys, and never
writes files: every tool returns its result to the calling AI app. Running real
evaluations (which call model providers with the user's keys) stays a separate,
explicit command, eval_models.py.

Repository tools only read inside the workspace roots: the roots the MCP client
shares, else the MODEL_FINDER_ROOT environment variable, else the current
directory. A filesystem root or home directory is refused as a workspace.

Transport: newline-delimited JSON-RPC 2.0 on stdin/stdout (MCP stdio). Logs go
to stderr only.
"""
from __future__ import annotations

import json
import os
import sys
import traceback
import urllib.parse
from dataclasses import asdict
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

_HERE = Path(__file__).resolve().parent
# Plugin layout: <root>/mcp/server.py next to <root>/skills. PyPI wheel: model_finder_mcp/{server.py,skills}.
ROOT = _HERE.parent if (_HERE.parent / "skills").is_dir() else _HERE
PLUGIN_DIR = ROOT  # the installed plugin folder; never treated as the user's project
EVAL_DIR = ROOT / "skills" / "eval-models" / "scripts"
ROUTE_DIR = ROOT / "skills" / "route-models" / "scripts"
SIZE_DIR = ROOT / "skills" / "size-local-model" / "scripts"
for _p in (EVAL_DIR, ROUTE_DIR, SIZE_DIR):
    sys.path.insert(0, str(_p))

import mf_core as core  # noqa: E402
import eval_models  # noqa: E402
import repo_scan  # noqa: E402
import make_routing  # noqa: E402
import estimate_memory  # noqa: E402

SERVER_NAME = "model_finder_mcp"
SERVER_VERSION = "1.3.4"
PROTOCOL_VERSIONS = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")
MAX_MESSAGE_BYTES = 8 * 1024 * 1024
MAX_TEXT_CHARS = 1_000_000

INSTRUCTIONS = (
    "Model Finder helps choose the cheapest AI model that passes the user's own tests. Typical flow: "
    "modelfinder_audit_models (what the repo uses) -> modelfinder_draft_eval_examples (examples from the repo) -> "
    "agree checks with the user -> modelfinder_create_eval_config -> modelfinder_validate_eval_config -> the user "
    "runs eval_models.py with their own keys -> modelfinder_rank_eval_results -> modelfinder_generate_routing. "
    "modelfinder_estimate_cost and modelfinder_estimate_memory are planning calculators. Every tool returns "
    "markdown by default; pass response_format=\"json\" for the full result. These tools never call model "
    "providers, never read keys, and never write files. Verify model IDs and prices on official provider pages. "
    "If a tool says the project is unknown, call it again with path set to the absolute project directory."
)


class ToolError(ValueError):
    """A problem with tool input; returned to the client as an isError result."""


# --------------------------------------------------------------------------
# Argument helpers
# --------------------------------------------------------------------------
def _num(args: Dict[str, Any], key: str, required: bool = False, integer: bool = False,
         default: Any = None) -> Any:
    value = args.get(key, default)
    if value is None:
        if required:
            raise ToolError(f"'{key}' is required.")
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ToolError(f"'{key}' must be a number.")
    if integer:
        if isinstance(value, float) and not value.is_integer():
            raise ToolError(f"'{key}' must be a whole number.")
        return int(value)
    return float(value)


def _text(args: Dict[str, Any], key: str, max_chars: int = MAX_TEXT_CHARS) -> str:
    value = args.get(key)
    if not isinstance(value, str):
        raise ToolError(f"'{key}' must be a string.")
    if len(value) > max_chars:
        raise ToolError(f"'{key}' is longer than {max_chars:,} characters.")
    return value


def _obj(args: Dict[str, Any], key: str) -> Dict[str, Any]:
    value = args.get(key)
    if not isinstance(value, dict):
        raise ToolError(f"'{key}' must be a JSON object.")
    return value


# --------------------------------------------------------------------------
# Workspace roots
# --------------------------------------------------------------------------
class Workspace:
    def __init__(self) -> None:
        self.client_roots: List[Path] = []

    def set_client_roots(self, roots: Any) -> None:
        paths: List[Path] = []
        for item in roots if isinstance(roots, list) else []:
            uri = item.get("uri") if isinstance(item, dict) else None
            if not isinstance(uri, str) or not uri.startswith("file://"):
                continue
            parsed = urllib.parse.urlparse(uri)
            raw = urllib.parse.unquote(parsed.path)
            if len(raw) > 2 and raw[0] == "/" and raw[2] == ":":  # file:///C:/x on Windows
                raw = raw[1:]
            if parsed.netloc and parsed.netloc != "localhost":
                continue
            try:
                paths.append(Path(raw).resolve())
            except OSError:
                continue
        self.client_roots = paths

    def roots(self) -> List[Path]:
        """Workspace roots, or [] when the host gave no workspace and started us inside the plugin folder."""
        if self.client_roots:
            return self.client_roots
        env = os.environ.get("MODEL_FINDER_ROOT", "").strip()
        if env and "${" not in env and Path(env).is_dir():  # ignore an unsubstituted ${...} placeholder
            return [Path(env).resolve()]
        cwd = Path.cwd().resolve()
        if cwd == PLUGIN_DIR:
            # Agent Plugins hosts (e.g. Codex) start servers in the plugin root and pass no workspace.
            return []
        return [cwd]

    @staticmethod
    def _too_broad(path: Path) -> bool:
        return path == Path(path.anchor) or path == Path.home().resolve()

    def _unbound_target(self, requested: Any) -> Path:
        if isinstance(requested, str) and 0 < len(requested) < 4096 and Path(requested).is_absolute():
            target = Path(requested).resolve()
            if self._too_broad(target):
                raise ToolError(f"{target} is too broad to scan. Pass the project folder itself.")
            if target == PLUGIN_DIR:
                raise ToolError("'path' is the Model Finder plugin folder. Pass the user's project folder.")
            if not target.is_dir():
                raise ToolError(f"Not a directory: {target}")
            return target
        raise ToolError(
            "This host started the server without telling it which project is open. Call again with 'path' set "
            "to the absolute path of the user's project (your current working directory), e.g. "
            "\"/home/me/my-app\". Alternatively set MODEL_FINDER_ROOT in the MCP server's environment.")

    def resolve(self, requested: Any) -> Path:
        roots = self.roots()
        if not roots:
            return self._unbound_target(requested)
        for root in roots:
            if self._too_broad(root):
                raise ToolError(
                    f"The workspace is {root}, which is too broad to scan. Open the project folder in your "
                    "IDE, or set MODEL_FINDER_ROOT to the project directory.")
        if requested in (None, "", "."):
            target = roots[0]
        elif isinstance(requested, str) and len(requested) < 4096:
            candidate = Path(requested)
            target = (candidate if candidate.is_absolute() else roots[0] / candidate).resolve()
        else:
            raise ToolError("'path' must be a directory path string.")
        if not any(target == root or root in target.parents for root in roots):
            raise ToolError("'path' must be inside the workspace: " + ", ".join(str(r) for r in roots))
        if not target.is_dir():
            raise ToolError(f"Not a directory: {target}")
        return target


WORKSPACE = Workspace()


# --------------------------------------------------------------------------
# Tool implementations (return plain dicts; rendering happens in Server)
# --------------------------------------------------------------------------
AUDIT_DEFAULT_LIMIT = 50
DRAFT_DEFAULT_LIMIT = 30
MAX_PAGE = 200
FAMILIES = [fam for fam, _ in repo_scan._FAMILIES]


def _bool(args: Dict[str, Any], key: str, default: bool = False) -> bool:
    value = args.get(key, default)
    if not isinstance(value, bool):
        raise ToolError(f"'{key}' must be true or false.")
    return value


def _page_args(args: Dict[str, Any], default_limit: int) -> tuple:
    limit = _num(args, "limit", integer=True, default=default_limit)
    offset = _num(args, "offset", integer=True, default=0)
    if not 1 <= limit <= MAX_PAGE:
        raise ToolError(f"'limit' must be 1-{MAX_PAGE}.")
    if offset < 0:
        raise ToolError("'offset' must be 0 or more.")
    return limit, offset


# The estimator is shared with a CLI, so its messages use flag names; agents need the tool's argument names.
_MEMORY_ARG_NAMES = [("--layers", "layers"), ("--kv-heads", "kv_heads"), ("--head-dim", "head_dim"),
                     ("--context", "context"), ("params-b", "params_b"), ("overhead-pct", "overhead_pct"),
                     ("kv-bits", "kv_bits"), ("available-gib", "available_gib"), ("kv-heads", "kv_heads"),
                     ("head-dim", "head_dim")]


def t_estimate_memory(args: Dict[str, Any]) -> Dict[str, Any]:
    kwargs = dict(
        params_b=_num(args, "params_b", required=True), bits=_num(args, "bits", required=True),
        overhead_pct=_num(args, "overhead_pct", default=0.0),
        layers=_num(args, "layers", integer=True), kv_heads=_num(args, "kv_heads", integer=True),
        head_dim=_num(args, "head_dim", integer=True), context=_num(args, "context", integer=True),
        concurrency=_num(args, "concurrency", integer=True, default=1),
        kv_bits=_num(args, "kv_bits", default=16.0), available_gib=_num(args, "available_gib"))
    try:
        est = estimate_memory.estimate(**kwargs)
    except ValueError as exc:
        message = str(exc)
        for flag, arg in _MEMORY_ARG_NAMES:
            message = message.replace(flag, arg)
        raise ToolError(message) from None
    return asdict(est)


def t_estimate_cost(args: Dict[str, Any]) -> Dict[str, Any]:
    return core.estimate_monthly_cost(
        requests_per_month=_num(args, "requests_per_month", required=True),
        input_tokens=_num(args, "input_tokens", required=True),
        output_tokens=_num(args, "output_tokens", required=True),
        input_price=_num(args, "input_price_per_million", required=True),
        output_price=_num(args, "output_price_per_million", required=True),
        cached_fraction=_num(args, "cached_fraction", default=0.0),
        cached_input_price=_num(args, "cached_input_price_per_million"),
        pass_rate=_num(args, "pass_rate"))


def _protection(found: Dict[str, int]) -> Dict[str, Any]:
    personal, secrets = core.split_findings(found)
    return {"personal_data": personal, "secrets": secrets,
            "note": "Pattern-based: names, addresses and free-text personal details are not detected. "
                    "Only categories and counts are reported, never the matched values."}


def t_scan_sensitive_data(args: Dict[str, Any]) -> Dict[str, Any]:
    found = core.detect_sensitive(_text(args, "text"))
    result = _protection(found)
    result["clean"] = not found
    return result


def t_check_output(args: Dict[str, Any]) -> Dict[str, Any]:
    text = _text(args, "text")
    checks = core.validate_checks(args.get("checks"), "checks")
    failures = core.run_checks(text, checks)
    return {"passed": not failures, "failures": failures, "checks_run": len(checks)}


def _config_report(raw: Dict[str, Any]) -> Dict[str, Any]:
    try:
        cfg = eval_models.parse_config(raw)
    except core.ConfigError as exc:
        return {"valid": False, "error": str(exc),
                "next_step": "Fix the field named in the error and call the tool again."}
    findings = eval_models.scan_sent_data(cfg)
    totals = eval_models._totals(findings)
    personal, secrets = core.split_findings(totals)
    calls = len(cfg["candidates"]) * len(cfg["examples"]) * cfg["repeats"]
    if secrets:
        verdict = "blocked: inputs contain what look like API keys or private keys (no override)"
    elif personal:
        verdict = ("blocked unless the user confirms a lawful basis and re-runs with --allow-personal-data; "
                   "prefer redacted or synthetic examples")
    else:
        verdict = "clear"
    return {
        "valid": True,
        "plan": {"candidates": len(cfg["candidates"]), "examples": len(cfg["examples"]),
                 "repeats": cfg["repeats"], "api_calls": calls,
                 "providers_receiving_examples": sorted({c.provider for c in cfg["candidates"]})},
        "required_env_vars": sorted({c.api_key_env for c in cfg["candidates"] if c.api_key_env}),
        "unpriced_candidates": [c.id for c in cfg["candidates"] if c.price is None],
        "data_protection": {**_protection(totals), "by_source": findings, "run_verdict": verdict},
        "next_step": ("Save the config as JSON, then run a free dry run: python3 "
                      f"{EVAL_DIR / 'eval_models.py'} CONFIG.json --dry-run. The real run calls the providers "
                      "with the user's keys and costs money; get the user's consent first."),
    }


def t_create_eval_config(args: Dict[str, Any]) -> Dict[str, Any]:
    candidates = args.get("candidates")
    examples = args.get("examples")
    if not isinstance(candidates, list) or not isinstance(examples, list):
        raise ToolError("'candidates' and 'examples' must be lists. Each example needs 'input' and 'checks'.")
    settings = args.get("settings") if isinstance(args.get("settings"), dict) else {}
    config: Dict[str, Any] = {
        "task": args.get("task", "") if isinstance(args.get("task"), str) else "",
        "settings": {"max_output_tokens": 1024, "timeout_s": 60, **settings},
        "pass_threshold": args.get("pass_threshold", 0.9),
        "repeats": args.get("repeats", 1),
        "candidates": candidates,
        "examples": [{k: v for k, v in ex.items() if k in ("id", "input", "checks")} if isinstance(ex, dict) else ex
                     for ex in examples],
    }
    return {"config": config, **_config_report(config)}


def t_validate_eval_config(args: Dict[str, Any]) -> Dict[str, Any]:
    return _config_report(_obj(args, "config"))


def _eval_results(args: Dict[str, Any]) -> Dict[str, Any]:
    results = _obj(args, "results")
    if results.get("schema") != "model-finder-eval/1":
        raise ToolError("'results' must be the full results.json object written by eval_models.py "
                        "(it has \"schema\": \"model-finder-eval/1\"). Read the file and pass its contents.")
    rows = results.get("summary")
    needed = ("id", "pass_rate", "meets_threshold", "cost_known", "cost_per_pass_usd")
    if not isinstance(rows, list) or not all(isinstance(r, dict) and all(k in r for k in needed) for r in rows):
        raise ToolError("results.summary rows are missing required fields; pass the unmodified results.json.")
    return results


def t_rank_eval_results(args: Dict[str, Any]) -> Dict[str, Any]:
    results = _eval_results(args)
    rows = results["summary"]
    rec = eval_models.recommend(rows)
    try:
        cascade, dropped = make_routing.build_chain(results, None, False)
    except core.ConfigError:
        cascade, dropped = [], []

    def key(r: Dict[str, Any]) -> Any:
        cpp = r.get("cost_per_pass_usd")
        return (not r["meets_threshold"], cpp is None, cpp if cpp is not None else 0, -r["pass_rate"])

    ranked = [{k: r.get(k) for k in ("id", "model", "pass_rate", "meets_threshold", "cost_per_pass_usd",
                                     "total_cost_usd", "median_latency_ms", "p95_latency_ms", "errors")}
              for r in sorted(rows, key=key)]
    return {"recommendation": rec, "ranked": ranked, "cascade": cascade, "dominated": dropped,
            "data_protection": results.get("data_protection"),
            "caveat": "Rankings reflect this sample and these checks only; small samples are smoke tests."}


def t_generate_routing(args: Dict[str, Any]) -> Dict[str, Any]:
    results = _eval_results(args)
    guards = args.get("guards") or []
    chain = args.get("chain")
    if chain is not None and (not isinstance(chain, list) or not all(isinstance(c, str) for c in chain)):
        raise ToolError("'chain' must be a list of candidate ids from results.summary.")
    pii_policy = args.get("pii_policy", "warn")
    routing, cands, yaml_text = make_routing.build_routing(
        results, guards, chain or None, _bool(args, "include_unknown_cost"), pii_policy)
    return {
        "routing_json": routing,
        "litellm_config_yaml": yaml_text,
        "chain": [c.id for c in cands],
        "notes": routing["notes"],
        "how_to_use": ("Save routing_json as routing/routing.json. For the standalone router with quality "
                       f"guards, run: python3 {ROUTE_DIR / 'make_routing.py'} --results results.json --out routing "
                       "(it also copies router.py). LiteLLM fallbacks fire on API errors only. Nothing is deployed."),
    }


def t_audit_models(args: Dict[str, Any]) -> Dict[str, Any]:
    limit, offset = _page_args(args, AUDIT_DEFAULT_LIMIT)
    family = args.get("provider_family")
    if family is not None and family not in FAMILIES:
        raise ToolError(f"'provider_family' must be one of: {', '.join(FAMILIES)}.")
    hard_coded_only = _bool(args, "hard_coded_only")
    full = repo_scan.audit_models(WORKSPACE.resolve(args.get("path")))
    models = [m for m in full["models"]
              if (family is None or m["provider_family"] == family)
              and (not hard_coded_only or m["used_as_env_default"] == 0)]
    page = models[offset:offset + limit]
    more = offset + len(page) < len(models)
    full["models"] = page
    full["filters"] = {"provider_family": family, "hard_coded_only": hard_coded_only}
    full["pagination"] = {"total": len(models), "count": len(page), "offset": offset, "has_more": more,
                          "next_offset": offset + len(page) if more else None}
    return full


def t_draft_eval_examples(args: Dict[str, Any]) -> Dict[str, Any]:
    limit, offset = _page_args(args, DRAFT_DEFAULT_LIMIT)
    return repo_scan.extract_examples(WORKSPACE.resolve(args.get("path")), limit, offset)


# --------------------------------------------------------------------------
# Markdown rendering (default response format; JSON is always in structuredContent)
# --------------------------------------------------------------------------
def _usd(value: Any) -> str:
    if value is None:
        return "unknown"
    value = round(value, 10)
    return f"${value:.6f}" if 0 < abs(value) < 0.01 else f"${value:,.2f}"


def _pct(value: Any) -> str:
    return "n/a" if value is None else f"{value:.0%}"


def _code(text: str, lang: str = "") -> str:
    return f"```{lang}\n{text.rstrip()}\n```"


def _more(p: Dict[str, Any]) -> str:
    shown = f"Showing {p['offset'] + 1 if p['count'] else 0}-{p['offset'] + p['count']} of {p['total']}."
    return shown + (f" Call again with offset={p['next_offset']} for more." if p["has_more"] else "")


def md_audit(r: Dict[str, Any]) -> str:
    out = [f"## AI models in {r['root']}", "", _more(r["pagination"]),
           f"Files scanned: {r['files_scanned']}. Skipped: {r['skipped'] or 'none'}."]
    if r["models"]:
        out += ["", "| Model | Provider | Route | Uses | Files | Hard-coded | Locations |", "|---|---|---|---|---|---|---|"]
        for m in r["models"]:
            locs = ", ".join(m["locations"][:3]) + (" ..." if len(m["locations"]) > 3 else "")
            out.append(f"| `{m['id']}` | {m['provider_family']} | {', '.join(m['routes']) or '-'} | {m['occurrences']} | "
                       f"{m['files']} | {'yes' if m['used_as_env_default'] == 0 else 'no (env default)'} | {locs} |")
        notes = sorted({n for m in r["models"] for n in m["notes"] if "latest" in n})
        out += [f"- {n}" for n in notes]
    else:
        out += ["", "No model IDs found for these filters."]
    if r["sdks"]:
        out += ["", "**AI SDKs:** " + "; ".join(f"`{s['name']}` ({', '.join(s['found_as'])}, {s['files']} files)"
                                               for s in r["sdks"])]
    out += ["", *[f"- {n}" for n in r["notes"]]]
    return "\n".join(out)


def md_drafts(r: Dict[str, Any]) -> str:
    out = ["## Eval example drafts", "", _more(r["pagination"]),
           f"Dropped for privacy: {r['excluded']['examples']} ({core.describe_findings(r['excluded']['categories'])})."]
    for d in r["drafts"]:
        text = d["input"] if len(d["input"]) <= 600 else d["input"][:600] + " ..."
        out += ["", f"### {d['id']}", f"Source: `{d['source']}`", "", "> " + text.replace("\n", "\n> ")]
        if d.get("reference_output") is not None:
            out.append(f"Reference output: `{d['reference_output'][:200]}`")
        if d["has_template_vars"]:
            out.append(f"Template variables to fill: {', '.join(d['template_vars'])}")
    out += ["", "**Next steps**", *[f"- {s}" for s in r["next_steps"]]]
    return "\n".join(out)


def md_config(r: Dict[str, Any]) -> str:
    out = []
    if not r["valid"]:
        out += ["**Config is not valid.** " + r["error"], r["next_step"]]
    else:
        p, dp = r["plan"], r["data_protection"]
        out += ["**Config is valid.**",
                f"- API calls: {p['api_calls']} ({p['candidates']} models x {p['examples']} examples x {p['repeats']} repeats)",
                f"- Providers that receive the examples: {', '.join(p['providers_receiving_examples'])}",
                f"- Environment variables to set: {', '.join(r['required_env_vars']) or 'none'}",
                f"- Models without a verified price: {', '.join(r['unpriced_candidates']) or 'none'}",
                f"- Privacy check: {dp['run_verdict']} (personal data: {core.describe_findings(dp['personal_data'])}; "
                f"secrets: {dp['secrets']})",
                "", r["next_step"]]
    if "config" in r:
        out += ["", "Config to save as JSON:", _code(json.dumps(r["config"], indent=2), "json")]
    return "\n".join(out)


def md_check(r: Dict[str, Any]) -> str:
    if r["passed"]:
        return f"**Passed** all {r['checks_run']} checks."
    return f"**Failed** {len(r['failures'])} of {r['checks_run']} checks:\n" + "\n".join(f"- {f}" for f in r["failures"])


def md_rank(r: Dict[str, Any]) -> str:
    rec = r["recommendation"]
    out = [f"**Cheapest model meeting the threshold:** {rec['cheapest_passing'] or 'none with a known cost'}"]
    if rec["passing_unknown_cost"]:
        out.append(f"Also met the threshold, cost unknown: {', '.join(rec['passing_unknown_cost'])}")
    out += ["", "| Model | Pass rate | Meets threshold | Cost per pass | Median latency |", "|---|---|---|---|---|"]
    for row in r["ranked"]:
        lat = "-" if row["median_latency_ms"] is None else f"{row['median_latency_ms']:,.0f} ms"
        out.append(f"| {row['id']} | {_pct(row['pass_rate'])} | {'yes' if row['meets_threshold'] else 'no'} | "
                   f"{_usd(row['cost_per_pass_usd'])} | {lat} |")
    out += ["", f"Cascade: {' -> '.join(r['cascade']) or 'none'}. Dropped as dominated: {', '.join(r['dominated']) or 'none'}.",
            r["caveat"]]
    return "\n".join(out)


def md_routing(r: Dict[str, Any]) -> str:
    out = [f"**Routing chain:** {' -> '.join(r['chain'])}",
           f"Personal-data policy: {r['routing_json']['pii_policy']}. Guards: {len(r['routing_json']['guards'])}.",
           *[f"- {n}" for n in r["notes"]], "", r["how_to_use"], "", "routing.json:",
           _code(json.dumps(r["routing_json"], indent=2), "json"), "", "litellm.config.yaml:",
           _code(r["litellm_config_yaml"], "yaml")]
    return "\n".join(out)


def md_cost(r: Dict[str, Any]) -> str:
    out = [f"- Cost per request: {_usd(r['cost_per_request_usd'])}", f"- Monthly cost: {_usd(r['monthly_cost_usd'])}"]
    if "cost_per_accepted_result_usd" in r:
        out += [f"- Cost per accepted result: {_usd(r['cost_per_accepted_result_usd'])}",
                f"- Monthly cost including retries: {_usd(r['monthly_cost_with_retries_usd'])}"]
    return "\n".join(out + ["", "Assumptions:", *[f"- {a}" for a in r["assumptions"]]])


def md_memory(r: Dict[str, Any]) -> str:
    out = [f"- Weights: {r['weights_gib']:,.2f} GiB"]
    if r["kv_cache_gib"] is not None:
        out.append(f"- KV cache: {r['kv_cache_gib']:,.2f} GiB ({r['kv_per_token_kib']:,.1f} KiB per token)")
    out += [f"- Overhead: {r['overhead_gib']:,.2f} GiB", f"- **Total: {r['total_gib']:,.2f} GiB**"]
    if r["headroom_gib"] is not None:
        word = "spare" if r["headroom_gib"] >= 0 else "over budget"
        out.append(f"- Headroom: {abs(r['headroom_gib']):,.2f} GiB {word}")
    return "\n".join(out + ["", *[f"- {c}" for c in r["caveats"]]])


def md_scan(r: Dict[str, Any]) -> str:
    if r["clean"]:
        return "**No personal data or secrets detected.** " + r["note"]
    return (f"**Detected** personal data: {core.describe_findings(r['personal_data'])}; secrets: {r['secrets']}.\n"
            + r["note"])


# --------------------------------------------------------------------------
# Tool catalog
# --------------------------------------------------------------------------
_NUM = {"type": "number"}
_INT = {"type": "integer"}
_FORMAT = {"type": "string", "enum": ["markdown", "json"], "default": "markdown",
           "description": "markdown (default) for a readable summary, json for the full machine-readable result."}
_LIMIT = lambda default: {"type": "integer", "minimum": 1, "maximum": MAX_PAGE, "default": default,
                          "description": f"Items per page (1-{MAX_PAGE}, default {default})."}
_OFFSET = {"type": "integer", "minimum": 0, "default": 0, "description": "Items to skip; use next_offset from the previous page."}
_CHECKS = {
    "type": "array", "minItems": 1, "maxItems": 50,
    "description": "Deterministic checks; all must pass. Types: contains, not_contains, exact (value, ignore_case?), "
                   "regex (pattern), json_keys (keys), max_chars (value). Example: "
                   "[{\"type\": \"json_keys\", \"keys\": [\"category\"]}, {\"type\": \"contains\", \"value\": \"refund\"}]",
    "items": {"type": "object", "required": ["type"], "properties": {
        "type": {"type": "string", "enum": list(core.CHECK_TYPES)},
        "value": {"description": "String for contains/not_contains/exact; positive integer for max_chars."},
        "pattern": {"type": "string", "description": "Regular expression for regex (max 500 chars)."},
        "keys": {"type": "array", "items": {"type": "string"}, "description": "Required top-level JSON keys for json_keys."},
        "ignore_case": {"type": "boolean", "description": "Case-insensitive contains/not_contains/exact."}}},
}
_CANDIDATE = {"type": "object", "required": ["id", "provider", "model"], "properties": {
    "id": {"type": "string", "description": "Short unique label, e.g. \"gemini-lite\"."},
    "provider": {"type": "string", "enum": list(core.PROVIDERS),
                 "description": "API format. Use openai_compatible for OpenRouter, Ollama, vLLM or gateways."},
    "model": {"type": "string", "description": "Exact provider model ID, verified from official docs."},
    "api_key_env": {"type": "string", "description": "Name of the environment variable holding the key, never the key."},
    "base_url": {"type": "string", "description": "HTTPS endpoint (http only for localhost). Required for openai_compatible."},
    "price_per_million": {"type": ["object", "null"], "description": "{input, output, cached_input?, source, checked} "
                          "in USD per million tokens from the official pricing page, or null if not verified."}}}
_RESULTS = {"type": "object", "description": "The full results.json object written by eval_models.py."}
_PATH = {"type": "string", "description": "Directory inside the workspace, relative to the project root (e.g. \"services/api\"). "
                                          "Defaults to the project root. If a call fails because the project is unknown, "
                                          "pass the absolute path of the project (your current working directory)."}


def _schema(props: Dict[str, Any], required: List[str]) -> Dict[str, Any]:
    return {"type": "object", "properties": {**props, "response_format": _FORMAT}, "required": required,
            "additionalProperties": False}


def _out(required: List[str], **props: Any) -> Dict[str, Any]:
    return {"type": "object", "required": required, "properties": props}


_PAGINATION = {"type": "object", "properties": {"total": _INT, "count": _INT, "offset": _INT,
                                                "has_more": {"type": "boolean"},
                                                "next_offset": {"type": ["integer", "null"]}}}

TOOLS: List[Dict[str, Any]] = [
    {"name": "modelfinder_audit_models", "title": "Audit AI models in the repo", "handler": t_audit_models,
     "render": md_audit,
     "description": "List AI model IDs (quoted literals) and AI SDKs used in the repository, with file:line locations, "
                    "provider family, route hints (Bedrock, Vertex AI, Azure, OpenRouter), usage counts and whether each "
                    "ID is hard-coded or an environment-variable default. Read-only; skips secret-like files and "
                    "dependency folders; never returns line content. Results are sorted by usage and paginated.",
     "inputSchema": _schema({"path": _PATH, "limit": _LIMIT(AUDIT_DEFAULT_LIMIT), "offset": _OFFSET,
                             "provider_family": {"type": "string", "enum": FAMILIES,
                                                 "description": "Only models from this family, e.g. \"anthropic\"."},
                             "hard_coded_only": {"type": "boolean", "default": False,
                                                 "description": "Only IDs not read from configuration or environment."}},
                            []),
     "outputSchema": _out(["root", "models", "sdks", "summary", "pagination"], models={"type": "array"},
                          sdks={"type": "array"}, summary={"type": "object"}, pagination=_PAGINATION)},
    {"name": "modelfinder_draft_eval_examples", "title": "Draft eval examples from the repo",
     "handler": t_draft_eval_examples, "render": md_drafts,
     "description": "Draft eval examples from prompt files and fixtures (prompts/, evals/, fixtures/, *.prompt.md, and "
                    "JSON/JSONL with input, prompt or chat messages). Drops any candidate with detected personal data "
                    "or secrets and reports only categories and counts. Drafts have empty checks: agree checks with the "
                    "user before modelfinder_create_eval_config. Paginated; ids are stable across pages.",
     "inputSchema": _schema({"path": _PATH, "limit": _LIMIT(DRAFT_DEFAULT_LIMIT), "offset": _OFFSET}, []),
     "outputSchema": _out(["drafts", "excluded", "pagination"], drafts={"type": "array"}, excluded={"type": "object"},
                          pagination=_PAGINATION)},
    {"name": "modelfinder_create_eval_config", "title": "Create an eval config", "handler": t_create_eval_config,
     "render": md_config,
     "description": "Assemble an eval config from candidate models, examples with checks, and settings; validate it and "
                    "screen the examples for personal data and secrets. Returns the config to save as JSON for "
                    "eval_models.py. Keys are referenced by environment variable name only.",
     "inputSchema": _schema({
         "task": {"type": "string", "description": "One-line description of what the model must do."},
         "candidates": {"type": "array", "minItems": 1, "maxItems": 10, "items": _CANDIDATE,
                        "description": "1-10 models to compare."},
         "examples": {"type": "array", "minItems": 1, "maxItems": 500, "description": "Inputs with the checks each reply must pass.",
                      "items": {"type": "object", "required": ["input", "checks"],
                                "properties": {"id": {"type": "string"}, "input": {"type": "string"}, "checks": _CHECKS}}},
         "settings": {"type": "object", "description": "max_output_tokens (default 1024), timeout_s (default 60), "
                                                       "temperature, system (system prompt)."},
         "pass_threshold": {**_NUM, "minimum": 0, "maximum": 1, "default": 0.9,
                            "description": "Share of calls that must pass every check (0-1)."},
         "repeats": {**_INT, "minimum": 1, "maximum": 10, "default": 1, "description": "Runs per example (3+ for noisy tasks)."}},
         ["candidates", "examples"]),
     "outputSchema": _out(["config", "valid"], config={"type": "object"}, valid={"type": "boolean"})},
    {"name": "modelfinder_validate_eval_config", "title": "Validate an eval config", "handler": t_validate_eval_config,
     "render": md_config,
     "description": "Check an eval config before running: schema, no keys in the config, HTTPS endpoints, no template "
                    "placeholders, valid checks. Reports API call count, required environment variable names, unpriced "
                    "models, and whether the personal-data guard would block the run. Makes no network calls.",
     "inputSchema": _schema({"config": {"type": "object", "description": "The eval config object (as saved for eval_models.py)."}},
                            ["config"]),
     "outputSchema": _out(["valid"], valid={"type": "boolean"})},
    {"name": "modelfinder_check_output", "title": "Test a reply against checks", "handler": t_check_output,
     "render": md_check,
     "description": "Run deterministic checks on one model reply. Use it to design eval checks and routing guards before "
                    "spending money on a run.",
     "inputSchema": _schema({"text": {"type": "string", "description": "The model reply to test."}, "checks": _CHECKS},
                            ["text", "checks"]),
     "outputSchema": _out(["passed", "failures", "checks_run"], passed={"type": "boolean"}, failures={"type": "array"},
                          checks_run=_INT)},
    {"name": "modelfinder_rank_eval_results", "title": "Rank eval results", "handler": t_rank_eval_results,
     "render": md_rank,
     "description": "Read a results.json object and return the cheapest model that met the pass threshold, ranked by cost "
                    "per passing call, plus the cost/reliability cascade and models dropped as dominated.",
     "inputSchema": _schema({"results": _RESULTS}, ["results"]),
     "outputSchema": _out(["recommendation", "ranked", "cascade", "dominated"], recommendation={"type": "object"},
                          ranked={"type": "array"}, cascade={"type": "array"}, dominated={"type": "array"})},
    {"name": "modelfinder_generate_routing", "title": "Generate cheapest-first routing", "handler": t_generate_routing,
     "render": md_routing,
     "description": "Turn a results.json object into a cheapest-first routing.json (with guards and a personal-data "
                    "policy) and a LiteLLM proxy config. Returns both; nothing is written or deployed.",
     "inputSchema": _schema({"results": _RESULTS, "guards": {**_CHECKS, "minItems": 0,
                                                            "description": "Checks applied to every production reply; "
                                                                           "a failure escalates to the next model."},
                             "chain": {"type": "array", "items": {"type": "string"},
                                       "description": "Explicit model order (candidate ids), overriding cost order."},
                             "include_unknown_cost": {"type": "boolean", "default": False,
                                                      "description": "Append passing models whose price is unknown."},
                             "pii_policy": {"type": "string", "enum": list(make_routing.PII_POLICIES), "default": "warn",
                                            "description": "block: never send prompts with personal data or secrets; "
                                                           "warn: send and report; off: no check."}}, ["results"]),
     "outputSchema": _out(["routing_json", "litellm_config_yaml", "chain", "notes"], routing_json={"type": "object"},
                          litellm_config_yaml={"type": "string"}, chain={"type": "array"}, notes={"type": "array"})},
    {"name": "modelfinder_estimate_cost", "title": "Estimate monthly token cost", "handler": t_estimate_cost,
     "render": md_cost,
     "description": "Planning estimate of monthly token cost from requests, average tokens per request and USD-per-million "
                    "prices, with optional cached-input share and pass rate (cost per accepted result, counting retries). "
                    "Prices must come from the provider's official pricing page.",
     "inputSchema": _schema({
         "requests_per_month": {**_NUM, "minimum": 0, "description": "e.g. 100000"},
         "input_tokens": {**_NUM, "minimum": 0, "description": "Average input tokens per request."},
         "output_tokens": {**_NUM, "minimum": 0, "description": "Average output tokens per request (include reasoning tokens)."},
         "input_price_per_million": {**_NUM, "minimum": 0, "description": "USD per 1M input tokens."},
         "output_price_per_million": {**_NUM, "minimum": 0, "description": "USD per 1M output tokens."},
         "cached_fraction": {**_NUM, "minimum": 0, "maximum": 1, "default": 0,
                             "description": "Share of input tokens billed at the cached rate (0-1)."},
         "cached_input_price_per_million": {**_NUM, "minimum": 0, "description": "Required when cached_fraction > 0."},
         "pass_rate": {**_NUM, "exclusiveMinimum": 0, "maximum": 1,
                       "description": "Optional eval pass rate; failures are assumed retried."}},
         ["requests_per_month", "input_tokens", "output_tokens", "input_price_per_million", "output_price_per_million"]),
     "outputSchema": _out(["cost_per_request_usd", "monthly_cost_usd", "assumptions"], cost_per_request_usd=_NUM,
                          monthly_cost_usd=_NUM, assumptions={"type": "array"})},
    {"name": "modelfinder_estimate_memory", "title": "Estimate local model memory", "handler": t_estimate_memory,
     "render": md_memory,
     "description": "Estimate memory to run an open-weight model locally: weights at a precision plus KV cache for a "
                    "context length and concurrency (standard MHA/GQA attention only), with headroom against available "
                    "memory. Give all four of layers, kv_heads, head_dim and context to include the KV cache.",
     "inputSchema": _schema({
         "params_b": {**_NUM, "description": "Total stored parameters in billions (for MoE, all experts)."},
         "bits": {**_NUM, "description": "Effective bits per weight: 16, 8, about 4.5 for common 4-bit formats."},
         "overhead_pct": {**_NUM, "minimum": 0, "maximum": 200, "default": 0, "description": "Allowance on top, in percent."},
         "layers": {**_INT, "description": "num_hidden_layers from the model config."},
         "kv_heads": {**_INT, "description": "num_key_value_heads (or num_attention_heads if absent)."},
         "head_dim": {**_INT, "description": "head_dim, or hidden_size / num_attention_heads."},
         "context": {**_INT, "description": "Context tokens per sequence actually used."},
         "concurrency": {**_INT, "minimum": 1, "default": 1, "description": "Sequences served at once."},
         "kv_bits": {**_NUM, "default": 16, "description": "KV cache precision in bits."},
         "available_gib": {**_NUM, "minimum": 0, "description": "GPU or unified memory available, in GiB."}},
         ["params_b", "bits"]),
     "outputSchema": _out(["weights_gib", "total_gib", "caveats"], weights_gib=_NUM, total_gib=_NUM,
                          caveats={"type": "array"})},
    {"name": "modelfinder_scan_sensitive_data", "title": "Scan text for personal data and secrets",
     "handler": t_scan_sensitive_data, "render": md_scan,
     "description": "Detect Aadhaar (Verhoeff checked), PAN, payment cards (Luhn checked), email addresses, UPI IDs, Indian "
                    "mobile numbers and API or private keys in text. Returns categories and counts only, never the values.",
     "inputSchema": _schema({"text": {"type": "string", "description": "Text to scan, up to 1,000,000 characters."}}, ["text"]),
     "outputSchema": _out(["personal_data", "secrets", "clean"], personal_data={"type": "object"}, secrets=_INT,
                          clean={"type": "boolean"})},
]
for _tool in TOOLS:
    _tool["annotations"] = {"title": _tool["title"], "readOnlyHint": True, "destructiveHint": False,
                            "idempotentHint": True, "openWorldHint": False}
BY_NAME: Dict[str, Dict[str, Any]] = {t["name"]: t for t in TOOLS}


# --------------------------------------------------------------------------
# JSON-RPC / MCP plumbing
# --------------------------------------------------------------------------
class Server:
    def __init__(self, write: Callable[[Dict[str, Any]], None]) -> None:
        self.write = write
        self.protocol = PROTOCOL_VERSIONS[0]
        self.client_supports_roots = False
        self._next_id = 0
        self._pending_roots: Optional[str] = None

    def _request_roots(self) -> None:
        self._next_id += 1
        self._pending_roots = f"model-finder-roots-{self._next_id}"
        self.write({"jsonrpc": "2.0", "id": self._pending_roots, "method": "roots/list"})

    def _tool_list(self) -> List[Dict[str, Any]]:
        modern = self.protocol >= "2025-06-18"
        out = []
        for t in TOOLS:
            entry = {"name": t["name"], "description": t["description"], "inputSchema": t["inputSchema"],
                     "annotations": t["annotations"]}
            if modern:
                entry["title"] = t["title"]
                entry["outputSchema"] = t["outputSchema"]
            out.append(entry)
        return out

    def _call_tool(self, params: Dict[str, Any]) -> Dict[str, Any]:
        name = params.get("name")
        tool = BY_NAME.get(name)
        if tool is None:
            raise LookupError(f"Unknown tool: {name!r}. Available: {', '.join(BY_NAME)}")
        args = params.get("arguments") or {}
        if not isinstance(args, dict):
            return self._error_result("'arguments' must be an object.")
        allowed = set(tool["inputSchema"]["properties"])
        unknown = sorted(set(args) - allowed)
        if unknown:
            return self._error_result(f"Unknown argument(s) {unknown} for {name}. Valid arguments: {', '.join(sorted(allowed))}.")
        fmt = args.pop("response_format", "markdown")
        if fmt not in ("markdown", "json"):
            return self._error_result("'response_format' must be \"markdown\" or \"json\".")
        try:
            result = tool["handler"](args)
        except (ToolError, core.ConfigError, ValueError, TypeError) as exc:
            return self._error_result(str(exc))
        except Exception:  # pragma: no cover - defensive
            traceback.print_exc(file=sys.stderr)
            return self._error_result("Internal error in Model Finder; see the server log.")
        text = tool["render"](result) if fmt == "markdown" else json.dumps(result, indent=2)
        payload: Dict[str, Any] = {"content": [{"type": "text", "text": text}], "isError": False}
        if self.protocol >= "2025-06-18":
            payload["structuredContent"] = result
        return payload

    @staticmethod
    def _error_result(message: str) -> Dict[str, Any]:
        return {"content": [{"type": "text", "text": f"Error: {message}"}], "isError": True}

    def handle(self, msg: Any) -> Optional[Dict[str, Any]]:
        if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0":
            return {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Invalid Request"}}
        method = msg.get("method")
        msg_id = msg.get("id")
        if method is None:  # a response to one of our requests
            if msg_id is not None and msg_id == self._pending_roots:
                self._pending_roots = None
                WORKSPACE.set_client_roots((msg.get("result") or {}).get("roots"))
            return None
        is_notification = "id" not in msg
        params = msg.get("params") if isinstance(msg.get("params"), dict) else {}
        try:
            if method == "initialize":
                requested = params.get("protocolVersion")
                self.protocol = requested if requested in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0]
                caps = params.get("capabilities") or {}
                self.client_supports_roots = isinstance(caps, dict) and "roots" in caps
                result: Any = {"protocolVersion": self.protocol,
                               "capabilities": {"tools": {"listChanged": False}},
                               "serverInfo": {"name": SERVER_NAME, "title": "Model Finder", "version": SERVER_VERSION},
                               "instructions": INSTRUCTIONS}
            elif method in ("notifications/initialized", "notifications/roots/list_changed"):
                if self.client_supports_roots:
                    self._request_roots()
                return None
            elif method == "ping":
                result = {}
            elif method == "tools/list":
                result = {"tools": self._tool_list()}
            elif method == "tools/call":
                result = self._call_tool(params)
            elif isinstance(method, str) and method.startswith("notifications/"):
                return None
            else:
                if is_notification:
                    return None
                return {"jsonrpc": "2.0", "id": msg_id,
                        "error": {"code": -32601, "message": f"Method not found: {method}"}}
        except LookupError as exc:
            return None if is_notification else {"jsonrpc": "2.0", "id": msg_id,
                                                 "error": {"code": -32602, "message": str(exc)}}
        if is_notification:
            return None
        return {"jsonrpc": "2.0", "id": msg_id, "result": result}


def _writer(stream: Any) -> Callable[[Any], None]:
    def write(message: Any) -> None:
        stream.write((json.dumps(message, separators=(",", ":")) + "\n").encode("utf-8"))
        stream.flush()
    return write


def serve(stdin: Any = None, stdout: Any = None) -> int:
    stdin = stdin or sys.stdin.buffer
    write = _writer(stdout or sys.stdout.buffer)
    server = Server(write)
    while True:
        line = stdin.readline(MAX_MESSAGE_BYTES + 1)
        if not line:
            return 0
        if len(line) > MAX_MESSAGE_BYTES:
            write({"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Message too large (8 MiB limit)"}})
            while line and not line.endswith(b"\n"):  # discard the rest of the oversized line
                line = stdin.readline(MAX_MESSAGE_BYTES)
            continue
        if not line.strip():
            continue
        try:
            msg = json.loads(line.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            write({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}})
            continue
        if isinstance(msg, list):  # JSON-RPC batch (older protocol revisions)
            replies = [r for r in (server.handle(m) for m in msg) if r is not None]
            if replies:
                write(replies if len(replies) > 1 else replies[0])
            continue
        reply = server.handle(msg)
        if reply is not None:
            write(reply)


def main(argv: Optional[List[str]] = None) -> int:
    argv = sys.argv if argv is None else argv
    if len(argv) > 1 and argv[1] in ("-h", "--help"):
        print(__doc__.strip())
        print("\nTools:")
        for t in TOOLS:
            print(f"  {t['name']:<34} {t['title']}")
        return 0
    if len(argv) > 1 and argv[1] == "--version":
        print(f"{SERVER_NAME} {SERVER_VERSION}")
        return 0
    return serve()


if __name__ == "__main__":
    sys.exit(main(sys.argv))
