#!/usr/bin/env python3
"""Cheapest-first model router with quality guards (standard library only).

Tries each model in routing.json in order. Escalates to the next model when a
call errors, returns empty text, or fails any guard check. Guards must be
generic (format, required fields, length) because they run on every request.

Library use:
    from router import load_routing, route
    routing = load_routing("routing.json")
    result = route("Your prompt", routing)

CLI use:
    python3 router.py routing.json "Your prompt"      # or pipe the prompt on stdin

Keys come from the environment variables named in routing.json. Nothing here
deploys, persists, or logs prompts.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mf_core as core  # noqa: E402

MAX_PROMPT_CHARS = 200_000
PII_POLICIES = ("block", "warn", "off")


def load_routing(path: str) -> Dict[str, Any]:
    """Load and re-validate routing.json (defends against hand edits)."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or raw.get("schema") != "model-finder-routing/1":
        raise core.ConfigError("Not a model-finder-routing/1 file.")
    chain_raw = raw.get("chain")
    if not isinstance(chain_raw, list) or not chain_raw:
        raise core.ConfigError("routing.json has an empty chain.")
    chain = [core.validate_candidate(c, i) for i, c in enumerate(chain_raw)]
    policy = raw.get("pii_policy", "warn")
    if policy not in PII_POLICIES:
        raise core.ConfigError(f"pii_policy must be one of {', '.join(PII_POLICIES)}.")
    return {
        "chain": chain,
        "pii_policy": policy,
        "settings": core.validate_settings(raw.get("settings")),
        "guards": core.validate_checks(raw.get("guards", []), "guards", allow_empty=True),
    }


def route(prompt: str, routing: Dict[str, Any]) -> Dict[str, Any]:
    """Return {"ok", "text", "model_id", "escalated", "attempts", "sensitive_data"}.

    Never raises on model failure. With pii_policy "block", a prompt containing
    detected personal data or secrets is not sent anywhere; with "warn" it is sent
    and the categories found are reported. Values are never included.
    """
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > MAX_PROMPT_CHARS:
        raise core.ConfigError(f"Prompt must be non-empty text up to {MAX_PROMPT_CHARS} chars.")
    policy = routing.get("pii_policy", "warn")
    found = core.detect_sensitive(prompt) if policy != "off" else {}
    if found and policy == "block":
        return {"ok": False, "text": None, "model_id": None, "escalated": False, "attempts": [],
                "sensitive_data": found,
                "blocked": "prompt contains personal data or secrets (pii_policy=block); nothing was sent"}
    attempts: List[Dict[str, Any]] = []
    last_text: Optional[str] = None
    for candidate in routing["chain"]:
        attempt: Dict[str, Any] = {"id": candidate.id, "ok": False, "reason": None,
                                   "latency_ms": None, "cost_usd": None}
        try:
            result = core.call_model(candidate, prompt, routing["settings"])
            attempt["latency_ms"] = round(result.latency_ms, 1)
            attempt["cost_usd"] = core.compute_cost(result.usage, candidate.price)
            failures = [] if result.text.strip() else ["empty output"]
            failures += core.run_checks(result.text, routing["guards"])
            last_text = result.text
            if failures:
                attempt["reason"] = "; ".join(failures)
            else:
                attempt["ok"] = True
                attempts.append(attempt)
                return {"ok": True, "text": result.text, "model_id": candidate.id,
                        "escalated": len(attempts) > 1, "attempts": attempts, "sensitive_data": found}
        except core.ModelCallError as exc:
            attempt["reason"] = str(exc)
        attempts.append(attempt)
    return {"ok": False, "text": last_text, "model_id": None, "escalated": len(attempts) > 1,
            "attempts": attempts, "sensitive_data": found}


def main(argv: List[str]) -> int:
    if len(argv) < 2:
        print(__doc__, file=sys.stderr)
        return 2
    try:
        routing = load_routing(argv[1])
        prompt = argv[2] if len(argv) > 2 else sys.stdin.read()
        result = route(prompt, routing)
    except (core.ConfigError, OSError, json.JSONDecodeError) as exc:
        print(f"Routing error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
