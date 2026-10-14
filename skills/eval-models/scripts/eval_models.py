#!/usr/bin/env python3
"""Run the same examples against several models and report evidence.

Usage:
  python3 eval_models.py CONFIG.json --out RESULTS_DIR [--dry-run] [--no-outputs] [--only id1,id2]

Writes RESULTS_DIR/results.json (machine-readable) and RESULTS_DIR/summary.md.
--dry-run validates the config and checks env vars without any network call.
Exit codes: 0 success, 1 runtime failure, 2 invalid configuration.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mf_core as core  # noqa: E402

MAX_CANDIDATES = 10
MAX_EXAMPLES = 500
MAX_REPEATS = 10
MAX_INPUT_CHARS = 200_000
OUTPUT_PREVIEW_CHARS = 4_000
TRUNCATION_REASONS = {"length", "max_tokens", "MAX_TOKENS"}


def load_config(path: Path) -> Dict[str, Any]:
    if path.stat().st_size > 20 * 1024 * 1024:
        raise core.ConfigError("Config file is larger than 20 MiB.")
    text = path.read_text(encoding="utf-8")
    if "REPLACE-with" in text:
        raise core.ConfigError("Config still contains template placeholders ('REPLACE-with...'). "
                               "Fill in verified model IDs and prices, or set price to null.")
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as exc:
        raise core.ConfigError(f"Config is not valid JSON: {exc}") from None
    if not isinstance(raw, dict):
        raise core.ConfigError("Config must be a JSON object.")

    cands_raw = raw.get("candidates")
    if not isinstance(cands_raw, list) or not 1 <= len(cands_raw) <= MAX_CANDIDATES:
        raise core.ConfigError(f"'candidates' must list 1-{MAX_CANDIDATES} models.")
    candidates = [core.validate_candidate(c, i) for i, c in enumerate(cands_raw)]
    ids = [c.id for c in candidates]
    if len(set(ids)) != len(ids):
        raise core.ConfigError("Candidate ids must be unique.")

    ex_raw = raw.get("examples")
    if not isinstance(ex_raw, list) or not 1 <= len(ex_raw) <= MAX_EXAMPLES:
        raise core.ConfigError(f"'examples' must list 1-{MAX_EXAMPLES} items.")
    examples: List[Dict[str, Any]] = []
    seen = set()
    for i, ex in enumerate(ex_raw):
        where = f"examples[{i}]"
        if not isinstance(ex, dict):
            raise core.ConfigError(f"{where} must be an object.")
        eid = ex.get("id", f"ex-{i + 1}")
        if not isinstance(eid, str) or not eid or len(eid) > 64 or eid in seen:
            raise core.ConfigError(f"{where}: 'id' must be a unique string up to 64 chars.")
        seen.add(eid)
        text = ex.get("input")
        if not isinstance(text, str) or not text.strip() or len(text) > MAX_INPUT_CHARS:
            raise core.ConfigError(f"{where}: 'input' must be non-empty text up to {MAX_INPUT_CHARS} chars.")
        examples.append({"id": eid, "input": text, "checks": core.validate_checks(ex.get("checks"), where)})

    repeats = raw.get("repeats", 1)
    if isinstance(repeats, bool) or not isinstance(repeats, int) or not 1 <= repeats <= MAX_REPEATS:
        raise core.ConfigError(f"'repeats' must be an integer 1-{MAX_REPEATS}.")
    threshold = core.number_in_range(raw.get("pass_threshold", 1.0), "pass_threshold", 0.0, 1.0)
    task = raw.get("task", "")
    if not isinstance(task, str) or len(task) > 2_000:
        raise core.ConfigError("'task' must be a short description string.")
    return {
        "task": task,
        "settings": core.validate_settings(raw.get("settings")),
        "candidates": candidates,
        "examples": examples,
        "repeats": repeats,
        "pass_threshold": threshold,
    }


def scan_sent_data(cfg: Dict[str, Any]) -> Dict[str, Dict[str, int]]:
    """Scan everything that would be sent to providers. Returns {source: {category: count}}."""
    findings: Dict[str, Dict[str, int]] = {}
    system = cfg["settings"].system
    if system:
        found = core.detect_sensitive(system)
        if found:
            findings["settings.system"] = found
    for ex in cfg["examples"]:
        found = core.detect_sensitive(ex["input"])
        if found:
            findings[f"example {ex['id']}"] = found
    return findings


def _totals(findings: Dict[str, Dict[str, int]]) -> Dict[str, int]:
    totals: Dict[str, int] = {}
    for found in findings.values():
        for key, count in found.items():
            totals[key] = totals.get(key, 0) + count
    return totals


def _percentile(values: List[float], pct: float) -> Optional[float]:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(pct * len(ordered)) - 1)]


def summarize(records: List[Dict[str, Any]], cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for cand in cfg["candidates"]:
        mine = [r for r in records if r["candidate"] == cand.id]
        if not mine:
            continue
        passed = sum(1 for r in mine if r["passed"])
        errors = sum(1 for r in mine if r["error"])
        latencies = [r["latency_ms"] for r in mine if r["latency_ms"] is not None and not r["error"]]
        costs = [r["cost_usd"] for r in mine]
        cost_known = all(c is not None for c in costs)
        total_cost = sum(c for c in costs if c is not None) if cost_known else None
        rate = passed / len(mine)
        rows.append({
            "id": cand.id,
            "model": cand.model,
            "provider": cand.provider,
            "calls": len(mine),
            "passed": passed,
            "errors": errors,
            "pass_rate": rate,
            "meets_threshold": rate >= cfg["pass_threshold"],
            "median_latency_ms": statistics.median(latencies) if latencies else None,
            "p95_latency_ms": _percentile(latencies, 0.95),
            "total_cost_usd": total_cost,
            "cost_per_pass_usd": (total_cost / passed) if (total_cost is not None and passed) else None,
            "cost_known": cost_known,
        })
    return rows


def recommend(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    passing = [r for r in rows if r["meets_threshold"]]
    # Rank by cost per passing call (cost per accepted result), not raw spend, so a cheap
    # model that fails often is not mistaken for a cheap solution.
    priced = sorted((r for r in passing if r["cost_known"]),
                    key=lambda r: (r["cost_per_pass_usd"] if r["cost_per_pass_usd"] is not None else float("inf"),
                                   -r["pass_rate"]))
    unpriced = [r["id"] for r in passing if not r["cost_known"]]
    return {
        "cheapest_passing": priced[0]["id"] if priced else None,
        "passing_unknown_cost": unpriced,
        "passing_ids_by_cost": [r["id"] for r in priced],
    }


def _fmt_usd(value: Optional[float]) -> str:
    if value is None:
        return "unknown"
    return f"${value:.6f}" if 0 < abs(value) < 0.01 else f"${value:,.2f}"


def _fmt_ms(value: Optional[float]) -> str:
    return "—" if value is None else f"{value:,.0f} ms"


def write_summary(path: Path, cfg: Dict[str, Any], rows: List[Dict[str, Any]], rec: Dict[str, Any],
                  records: List[Dict[str, Any]], started: str, protection: Dict[str, Any]) -> None:
    lines = [
        "# Model evaluation summary",
        "",
        f"- Task: {cfg['task'] or '(not described)'}",
        f"- Run started (UTC): {started}",
        f"- Examples: {len(cfg['examples'])} × repeats: {cfg['repeats']}",
        f"- Pass threshold: {cfg['pass_threshold']:.0%} of calls must pass every check",
        "",
        "| Candidate | Model | Pass rate | Errors | Median latency | p95 latency | Total cost | Cost / pass |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        mark = " ✅" if r["meets_threshold"] else ""
        lines.append(
            f"| {r['id']}{mark} | `{r['model']}` | {r['passed']}/{r['calls']} ({r['pass_rate']:.0%}) | "
            f"{r['errors']} | {_fmt_ms(r['median_latency_ms'])} | {_fmt_ms(r['p95_latency_ms'])} | "
            f"{_fmt_usd(r['total_cost_usd'])} | {_fmt_usd(r['cost_per_pass_usd'])} |"
        )
    lines += ["", "## Result", ""]
    if rec["cheapest_passing"]:
        lines.append(f"Cheapest candidate meeting the threshold on this sample (by cost per passing call): "
                     f"**{rec['cheapest_passing']}**.")
    else:
        lines.append("No candidate with a known cost met the threshold on this sample.")
    if rec["passing_unknown_cost"]:
        lines.append(f"Also met the threshold but cost is unknown (add a verified price): "
                     f"{', '.join(rec['passing_unknown_cost'])}.")
    lines += ["", "## Caveats", ""]
    if len(cfg["examples"]) < 10:
        lines.append(f"- Only {len(cfg['examples'])} examples: treat this as a smoke test, not evidence of fit.")
    lines.append("- Deterministic checks verify format and required content, not open-ended quality. "
                 "Review saved outputs for tasks like writing or summarization.")
    lines.append("- Latency is measured from this machine and includes network time.")
    lines.append("- Costs use the prices in the config; confirm the source and date before relying on them.")
    notes = sorted({n for r in records for n in r["notes"]})
    for note in notes:
        lines.append(f"- Observed: {note}.")
    lines += ["", "## Data protection", ""]
    detected = protection["personal_data_detected"]
    if detected:
        lines.append(f"- Personal data detected in sent inputs ({core.describe_findings(detected)}) and sent "
                     "with explicit approval (--allow-personal-data). Record the lawful basis for this "
                     "processing and delete these results when no longer needed.")
    else:
        lines.append("- No personal data or secrets detected in sent inputs by pattern checks "
                     "(names, addresses and free-text personal details are not detectable this way).")
    lines.append(f"- Model outputs saved in results.json: {'yes' if protection['outputs_saved'] else 'no'}.")
    failures = [r for r in records if not r["passed"]][:15]
    if failures:
        lines += ["", "## Sample failures", ""]
        for r in failures:
            reason = r["error"] or "; ".join(r["failed_checks"])
            lines.append(f"- {r['candidate']} / {r['example']} (run {r['repeat']}): {reason}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("config", type=Path)
    parser.add_argument("--out", type=Path, default=Path("model-eval-results"))
    parser.add_argument("--dry-run", action="store_true", help="validate only; no network calls")
    parser.add_argument("--no-outputs", action="store_true", help="do not save model outputs")
    parser.add_argument("--allow-personal-data", action="store_true",
                        help="send inputs even if personal data is detected (recorded in results)")
    parser.add_argument("--keep-outputs", action="store_true",
                        help="save model outputs even when personal data was allowed")
    parser.add_argument("--only", help="comma-separated candidate ids to run")
    args = parser.parse_args(argv)

    try:
        cfg = load_config(args.config)
        if args.only:
            wanted = {x.strip() for x in args.only.split(",") if x.strip()}
            unknown = wanted - {c.id for c in cfg["candidates"]}
            if unknown:
                raise core.ConfigError(f"--only names unknown candidates: {sorted(unknown)}")
            cfg["candidates"] = [c for c in cfg["candidates"] if c.id in wanted]
    except (core.ConfigError, OSError) as exc:
        print(f"Config error: {exc}", file=sys.stderr)
        return 2

    calls = len(cfg["candidates"]) * len(cfg["examples"]) * cfg["repeats"]
    missing_env = sorted({c.api_key_env for c in cfg["candidates"]
                          if c.api_key_env and not os.environ.get(c.api_key_env, "").strip()})
    unpriced = [c.id for c in cfg["candidates"] if c.price is None]
    print(f"Plan: {len(cfg['candidates'])} candidates × {len(cfg['examples'])} examples × "
          f"{cfg['repeats']} repeats = {calls} API calls.")
    if unpriced:
        print(f"No verified price for: {', '.join(unpriced)} (cost will be reported as unknown).")
    findings = scan_sent_data(cfg)
    totals = _totals(findings)
    personal, secrets = core.split_findings(totals)
    if findings:
        print("Sensitive data check (categories and counts only; values are never shown):")
        for source, found in findings.items():
            print(f"  {source}: {core.describe_findings(found)}")
    if secrets:
        print("Blocked: inputs contain what look like API keys or private keys. Remove them; "
              "secrets are never sent to providers, and there is no override.", file=sys.stderr)
        return 2
    if personal and not args.allow_personal_data:
        message = ("Personal data detected. Replace it with redacted or synthetic values. If you must "
                   "send it, confirm you have a lawful basis (for example consent) and that sending it to "
                   "these providers is permitted, then re-run with --allow-personal-data.")
        if args.dry_run:
            print(f"Dry run: the real run will be blocked. {message}")
            return 0
        print(f"Blocked: {message}", file=sys.stderr)
        return 2
    save_outputs = not args.no_outputs and (not personal or args.keep_outputs)
    if personal and not save_outputs and not args.no_outputs:
        print("Personal data allowed: model outputs will not be saved (use --keep-outputs to save them).")
    if args.dry_run:
        if missing_env:
            print(f"Dry run OK: config valid. Set before running: {', '.join(missing_env)}. No calls made.")
        else:
            print("Dry run OK: config valid, environment variables present. No calls made.")
        return 0
    if missing_env:
        print(f"Missing environment variables: {', '.join(missing_env)}", file=sys.stderr)
        return 2

    started = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    records: List[Dict[str, Any]] = []
    for cand in cfg["candidates"]:
        for ex in cfg["examples"]:
            for rep in range(1, cfg["repeats"] + 1):
                record: Dict[str, Any] = {
                    "candidate": cand.id, "example": ex["id"], "repeat": rep, "passed": False,
                    "failed_checks": [], "error": None, "latency_ms": None, "retries": 0,
                    "uncached_input_tokens": None, "cached_input_tokens": 0, "output_tokens": None,
                    "cost_usd": None, "notes": [],
                }
                try:
                    result = core.call_model(cand, ex["input"], cfg["settings"])
                    record["failed_checks"] = core.run_checks(result.text, ex["checks"])
                    record["passed"] = not record["failed_checks"]
                    record.update(latency_ms=round(result.latency_ms, 1), retries=result.retries,
                                  uncached_input_tokens=result.usage.uncached_input,
                                  cached_input_tokens=result.usage.cached_input,
                                  output_tokens=result.usage.output,
                                  cost_usd=core.compute_cost(result.usage, cand.price),
                                  notes=list(result.notes))
                    if result.raw_finish in TRUNCATION_REASONS:
                        record["notes"].append("output hit max_output_tokens (truncated)")
                    if save_outputs:
                        record["output"] = result.text[:OUTPUT_PREVIEW_CHARS]
                except core.ModelCallError as exc:
                    record["error"] = str(exc)
                records.append(record)
                status = "pass" if record["passed"] else ("error" if record["error"] else "fail")
                print(f"  {cand.id:<20} {ex['id']:<20} run {rep}: {status}")

    rows = summarize(records, cfg)
    rec = recommend(rows)
    protection = {
        "personal_data_detected": personal,
        "personal_data_allowed": bool(personal) and args.allow_personal_data,
        "outputs_saved": save_outputs,
        "detector": "pattern-based; does not detect names, addresses or free-text personal details",
    }
    try:
        args.out.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema": "model-finder-eval/1",
            "started_utc": started,
            "task": cfg["task"],
            "pass_threshold": cfg["pass_threshold"],
            "settings": {"max_output_tokens": cfg["settings"].max_output_tokens,
                         "timeout_s": cfg["settings"].timeout_s,
                         "temperature": cfg["settings"].temperature,
                         "system": cfg["settings"].system},
            "candidates": [c.public_dict() for c in cfg["candidates"]],
            "summary": rows,
            "recommendation": rec,
            "data_protection": protection,
            "records": records,
        }
        (args.out / "results.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
        write_summary(args.out / "summary.md", cfg, rows, rec, records, started, protection)
    except OSError as exc:
        print(f"Could not write results: {exc}", file=sys.stderr)
        return 1
    print(f"Done. Cheapest passing: {rec['cheapest_passing'] or 'none'}. "
          f"See {args.out / 'summary.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
