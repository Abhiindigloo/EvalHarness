#!/usr/bin/env python3
"""Read-only repository scanners for Model Finder (standard library only).

  audit     List AI model IDs and SDKs used in a repository.
  examples  Draft eval examples from prompt files and fixtures already in it.

Usage:
  python3 repo_scan.py audit [PATH]
  python3 repo_scan.py examples [PATH] [--max 30]

Privacy and safety:
  * Nothing is written and nothing is sent over the network.
  * Likely secret files (.env*, keys, certificates, credential stores) and
    dependency/build folders are skipped; symlinks are not followed.
  * The audit reports model IDs and file:line locations only, never line content.
  * Drafted examples that contain detected personal data or secrets are dropped,
    and only their categories and counts are reported.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mf_core as core  # noqa: E402

MAX_FILE_BYTES = 1_000_000
MAX_FILES = 5_000
MAX_LOCATIONS = 20
MAX_DRAFT_CHARS = 20_000
MAX_EXAMPLES_CAP = 200

SKIP_DIRS = {
    ".git", ".hg", ".svn", "node_modules", ".venv", "venv", "env", "__pycache__", ".mypy_cache",
    ".pytest_cache", ".ruff_cache", ".tox", "dist", "build", ".next", ".nuxt", "out", "target",
    "vendor", ".idea", ".vscode", ".gradle", "coverage", ".terraform", "site-packages", ".cache",
    "model-eval-results", "routing",
}
SECRET_NAME_RE = re.compile(
    r"(^\.env(\..*)?$|\.(pem|key|p12|pfx|jks|keystore|crt|cer|der)$|^id_(rsa|dsa|ecdsa|ed25519)|"
    r"(^|[._-])(credentials?|secrets?|tokens?|service[_-]?account)(\.(json|ya?ml|toml|txt|ini|cfg))?$|"
    r"\.netrc$|\.npmrc$|\.pypirc$)", re.IGNORECASE)
CODE_EXTS = {
    ".py", ".ipynb", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".go", ".java", ".kt", ".rb", ".php",
    ".cs", ".rs", ".swift", ".scala", ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".tf",
}
MANIFESTS = {"package.json", "requirements.txt", "requirements-dev.txt", "pyproject.toml", "Pipfile",
             "setup.cfg", "setup.py", "go.mod", "Gemfile", "pom.xml", "build.gradle"}

# --------------------------------------------------------------------------
# Walking
# --------------------------------------------------------------------------
def walk(root: Path, stats: Dict[str, int]) -> Iterator[Tuple[Path, str]]:
    """Yield (path, relative posix path) for readable text files under root."""
    count = 0
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = sorted(d for d in dirnames
                             if d not in SKIP_DIRS and not os.path.islink(os.path.join(dirpath, d)))
        for name in sorted(filenames):
            full = Path(dirpath) / name
            if full.is_symlink():
                continue
            if SECRET_NAME_RE.search(name):
                stats["skipped_secret_like"] = stats.get("skipped_secret_like", 0) + 1
                continue
            try:
                size = full.stat().st_size
            except OSError:
                continue
            if size > MAX_FILE_BYTES:
                stats["skipped_too_large"] = stats.get("skipped_too_large", 0) + 1
                continue
            count += 1
            if count > MAX_FILES:
                stats["truncated"] = 1
                return
            yield full, full.relative_to(root).as_posix()


def read_text(path: Path, stats: Dict[str, int]) -> Optional[str]:
    try:
        data = path.read_bytes()
    except OSError:
        return None
    if b"\x00" in data[:4096]:
        stats["skipped_binary"] = stats.get("skipped_binary", 0) + 1
        return None
    return data.decode("utf-8", errors="replace")


# --------------------------------------------------------------------------
# Model audit
# --------------------------------------------------------------------------
_FAMILIES = [
    ("anthropic", r"claude-[a-z0-9][a-z0-9.\-@:]*"),
    ("openai", r"(?:gpt-[0-9a-z][a-z0-9.\-]*|chatgpt-[a-z0-9.\-]+|o[1-9](?:-(?:mini|pro|preview|high|low)"
               r"[a-z0-9.\-]*)?|text-embedding-[a-z0-9.\-]+|whisper-[a-z0-9.\-]+|dall-e-[0-9]|tts-1[a-z0-9.\-]*)"),
    ("google", r"(?:gemini-[0-9a-z][a-z0-9.\-]*|gemma-?[0-9][a-z0-9.\-]*|text-embedding-0[0-9]{2}|imagen-[0-9a-z.\-]+)"),
    ("meta", r"(?:meta-)?llama-?[0-9][a-z0-9.\-]*"),
    ("mistral", r"(?:mistral|mixtral|codestral|ministral|pixtral|magistral|devstral)-[a-z0-9.\-]+"),
    ("deepseek", r"deepseek-[a-z0-9.\-]+"),
    ("alibaba", r"qwen[0-9][a-z0-9.\-]*"),
    ("xai", r"grok-[0-9a-z][a-z0-9.\-]*"),
    ("cohere", r"command-(?:r|a)(?:-[a-z0-9.\-]+|\+)?"),
]
_ROUTE_PREFIX = r"(?:(?P<route>[a-z_]+)/)?(?:(?P<region>[a-z]{2}|global)\.)?(?:(?P<vendor>anthropic|meta|mistral|cohere|amazon)\.)?"
MODEL_RE = re.compile(
    r"""(?P<q>["'`])""" + _ROUTE_PREFIX + r"(?P<id>" + "|".join(f"(?P<f_{fam}>{pat})" for fam, pat in _FAMILIES)
    + r")(?P=q)", re.IGNORECASE)
ENV_HINT_RE = re.compile(r"os\.environ|getenv|process\.env|System\.getenv|ENV\[|env\(|Environment\.Get", re.I)
ROUTE_NAMES = {"bedrock": "AWS Bedrock", "vertex_ai": "Vertex AI", "vertex": "Vertex AI", "azure": "Azure",
               "openrouter": "OpenRouter", "groq": "Groq", "together_ai": "Together AI", "ollama": "Ollama",
               "anthropic": "Anthropic API", "openai": "OpenAI API", "gemini": "Gemini API"}

_PY_SDKS = ["anthropic", "openai", "google.genai", "google.generativeai", "vertexai", "litellm", "mistralai",
            "cohere", "groq", "ollama", "together", "langchain_anthropic", "langchain_openai",
            "langchain_google_genai", "langchain_google_vertexai", "llama_index", "transformers", "vllm"]
PY_IMPORT_RE = re.compile(r"^\s*(?:import|from)\s+(" + "|".join(re.escape(s) for s in _PY_SDKS) + r")\b", re.M)
JS_IMPORT_RE = re.compile(
    r"""(?:from\s+|require\(\s*|import\(\s*)["'](@anthropic-ai/sdk|openai|@google/genai|@google/generative-ai|"""
    r"""@google-cloud/vertexai|ai|@ai-sdk/[a-z0-9-]+|@mistralai/mistralai|cohere-ai|groq-sdk|ollama|"""
    r"""@langchain/[a-z0-9-]+|@aws-sdk/client-bedrock-runtime)["']""")
_PY_PACKAGES = ["anthropic", "openai", "google-genai", "google-generativeai", "google-cloud-aiplatform", "litellm",
                "mistralai", "cohere", "groq", "ollama", "together", "langchain-anthropic", "langchain-openai",
                "langchain-google-genai", "llama-index", "transformers", "vllm"]
PY_PKG_RE = re.compile(r"""(?m)^\s*["']?(""" + "|".join(re.escape(p) for p in _PY_PACKAGES) + r""")(?:\[[^\]]*\])?\s*(?:[<>=!~;"',\]]|$)""",
                       re.IGNORECASE)
JS_PACKAGES_RE = re.compile(r"^(@anthropic-ai/sdk|openai|@google/genai|@google/generative-ai|@google-cloud/vertexai|ai|"
                            r"@ai-sdk/[a-z0-9-]+|@mistralai/mistralai|cohere-ai|groq-sdk|ollama|@langchain/[a-z0-9-]+|"
                            r"@aws-sdk/client-bedrock-runtime)$")


def _family(match: "re.Match[str]") -> str:
    for fam, _ in _FAMILIES:
        if match.group(f"f_{fam}"):
            return fam
    return "unknown"


def _add(store: Dict[str, Dict[str, Any]], key: str, location: str, kind: Optional[str] = None,
         **fields: Any) -> Dict[str, Any]:
    entry = store.setdefault(key, {"locations": [], "count": 0, "files": set(), "kinds": set(), **fields})
    if kind:
        entry["kinds"].add(kind)
    entry["count"] += 1
    entry["files"].add(location.rsplit(":", 1)[0])
    if len(entry["locations"]) < MAX_LOCATIONS:
        entry["locations"].append(location)
    return entry


def audit_models(root: Path) -> Dict[str, Any]:
    """Inventory model IDs (string literals) and AI SDKs in a repository."""
    root = Path(root).resolve()
    stats: Dict[str, int] = {}
    models: Dict[str, Dict[str, Any]] = {}
    sdks: Dict[str, Dict[str, Any]] = {}
    scanned = 0
    for path, rel in walk(root, stats):
        is_manifest = path.name in MANIFESTS
        if path.suffix.lower() not in CODE_EXTS and not is_manifest:
            continue
        text = read_text(path, stats)
        if text is None:
            continue
        scanned += 1
        lines = text.splitlines()
        for lineno, line in enumerate(lines, 1):
            if len(line) > 5_000:
                continue
            loc = f"{rel}:{lineno}"
            for m in MODEL_RE.finditer(line):
                model_id = m.group(0)[1:-1]  # exact literal, including any route/vendor prefix
                route = (m.group("route") or "").lower()
                vendor = (m.group("vendor") or "").lower()
                route_hint = ROUTE_NAMES.get(route) or ("AWS Bedrock" if vendor else None)
                entry = _add(models, model_id, loc, model=m.group("id"), provider_family=_family(m),
                             routes=set(), env_default=0)
                if route_hint:
                    entry["routes"].add(route_hint)
                if ENV_HINT_RE.search(line):
                    entry["env_default"] += 1
            if path.suffix == ".py" or path.suffix == ".ipynb":
                for m in PY_IMPORT_RE.finditer(line):
                    _add(sdks, m.group(1), loc, kind="python import")
            elif path.suffix in (".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx"):
                for m in JS_IMPORT_RE.finditer(line):
                    _add(sdks, m.group(1), loc, kind="js import")
        if is_manifest:
            if path.name == "package.json":
                try:
                    pkg = json.loads(text)
                except json.JSONDecodeError:
                    pkg = {}
                for section in ("dependencies", "devDependencies", "peerDependencies"):
                    for name in (pkg.get(section) or {}) if isinstance(pkg, dict) else {}:
                        if isinstance(name, str) and JS_PACKAGES_RE.match(name):
                            _add(sdks, name, f"{rel}:1", kind="dependency")
            else:
                for lineno, line in enumerate(lines, 1):
                    for m in PY_PKG_RE.finditer(line):
                        _add(sdks, m.group(1).lower(), f"{rel}:{lineno}", kind="dependency")

    model_rows = []
    for model_id, e in sorted(models.items(), key=lambda kv: (-kv[1]["count"], kv[0])):
        notes = []
        if model_id.lower().endswith("-latest"):
            notes.append("'-latest' alias: the model behind it can change without a code change.")
        if e["env_default"] == 0:
            notes.append("Hard-coded: not read from configuration or an environment variable.")
        model_rows.append({
            "id": model_id, "model": e["model"], "provider_family": e["provider_family"], "routes": sorted(e["routes"]),
            "occurrences": e["count"], "files": len(e["files"]), "locations": e["locations"],
            "used_as_env_default": e["env_default"], "notes": notes,
        })
    sdk_rows = [{"name": name, "found_as": sorted(e["kinds"]), "occurrences": e["count"], "files": len(e["files"]),
                 "locations": e["locations"]}
                for name, e in sorted(sdks.items(), key=lambda kv: (-kv[1]["count"], kv[0]))]
    families = sorted({m["provider_family"] for m in model_rows})
    return {
        "root": str(root),
        "files_scanned": scanned,
        "skipped": {k: v for k, v in stats.items() if k != "truncated"},
        "truncated": bool(stats.get("truncated")),
        "models": model_rows,
        "sdks": sdk_rows,
        "summary": {"distinct_models": len(model_rows), "provider_families": families,
                    "hard_coded_models": sum(1 for m in model_rows if m["used_as_env_default"] == 0)},
        "notes": [
            "Model IDs are found as quoted string literals; IDs built at runtime or loaded from config "
            "files outside the scanned types are not detected.",
            "Deprecation and retirement status is not checked; verify each ID on the provider's documentation.",
            "Line content is never returned, only file:line locations.",
        ],
    }


# --------------------------------------------------------------------------
# Eval examples from the repository
# --------------------------------------------------------------------------
PROMPT_DIRS = {"prompts", "prompt", "fixtures", "evals", "eval", "examples", "testdata", "test_data", "samples",
               "datasets", "golden", "goldens", "test_cases", "testcases"}
PROMPT_FILE_RE = re.compile(r"(\.prompt(\.(md|txt))?$|prompt[\w-]*\.(md|txt)$)", re.IGNORECASE)
DOC_NAME_RE = re.compile(r"^(readme|changelog|license|contributing|code_of_conduct)", re.IGNORECASE)
INPUT_KEYS = ("input", "prompt", "question", "query", "user_input", "instruction", "text", "message")
REFERENCE_KEYS = ("expected", "expected_output", "ideal", "reference", "answer", "target", "output", "completion")
TEMPLATE_RE = re.compile(r"\{\{\s*([A-Za-z_][\w.]*)\s*\}\}|\$\{([A-Za-z_][\w.]*)\}|\{([A-Za-z_][\w]*)\}|<<([A-Z_][A-Z0-9_]*)>>")


def _is_prompt_source(rel: str) -> bool:
    parts = rel.split("/")
    name = parts[-1]
    if DOC_NAME_RE.match(name):
        return False
    if PROMPT_FILE_RE.search(name):
        return True
    ext = os.path.splitext(name)[1].lower()
    return ext in (".txt", ".md", ".jsonl", ".json") and any(p.lower() in PROMPT_DIRS for p in parts[:-1])


def _records_from_json(value: Any) -> List[Dict[str, Any]]:
    if isinstance(value, list):
        return [v for v in value if isinstance(v, dict)]
    if isinstance(value, dict):
        for key in ("examples", "data", "items", "cases", "tests"):
            if isinstance(value.get(key), list):
                return [v for v in value[key] if isinstance(v, dict)]
        return [value]
    return []


def _input_of(record: Dict[str, Any]) -> Tuple[Optional[str], Optional[str]]:
    text: Optional[str] = None
    messages = record.get("messages")
    if isinstance(messages, list):
        users = [m.get("content") for m in messages
                 if isinstance(m, dict) and m.get("role") == "user" and isinstance(m.get("content"), str)]
        if users:
            text = users[-1]
    if text is None:
        for key in INPUT_KEYS:
            if isinstance(record.get(key), str):
                text = record[key]
                break
    reference = next((record[k] for k in REFERENCE_KEYS if isinstance(record.get(k), str)), None)
    return text, reference


def extract_examples(root: Path, max_examples: int = 30, offset: int = 0) -> Dict[str, Any]:
    """Draft eval examples from prompt files and fixtures; drop anything with detected sensitive data.

    Returns one page of drafts (offset, max_examples). Draft ids are assigned in scan order, so
    they stay the same from page to page.
    """
    root = Path(root).resolve()
    if isinstance(max_examples, bool) or not isinstance(max_examples, int) or not 1 <= max_examples <= MAX_EXAMPLES_CAP:
        raise core.ConfigError(f"max_examples must be an integer 1-{MAX_EXAMPLES_CAP}.")
    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
        raise core.ConfigError("offset must be a whole number of 0 or more.")
    stats: Dict[str, int] = {}
    drafts: List[Dict[str, Any]] = []
    excluded: Dict[str, int] = {}
    excluded_count = 0
    seen_hashes = set()
    used_ids = set()
    scanned = 0
    total_clean = 0

    def add(text: str, reference: Optional[str], source: str, stem: str) -> None:
        nonlocal excluded_count, total_clean
        text = text.strip()
        if not text or len(text) > MAX_DRAFT_CHARS:
            return
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        if digest in seen_hashes:
            return
        seen_hashes.add(digest)
        found = core.detect_sensitive(text + "\n" + (reference or ""))
        if found:
            excluded_count += 1
            for key, val in found.items():
                excluded[key] = excluded.get(key, 0) + val
            return
        index = total_clean
        total_clean += 1
        base = re.sub(r"[^A-Za-z0-9._-]+", "-", stem).strip("-")[:50] or "example"
        eid, n = base, 1
        while eid in used_ids:
            n += 1
            eid = f"{base}-{n}"
        used_ids.add(eid)
        if not offset <= index < offset + max_examples:
            return
        variables = sorted({next(g for g in m.groups() if g) for m in TEMPLATE_RE.finditer(text)})
        draft: Dict[str, Any] = {"id": eid, "input": text, "source": source, "checks": [],
                                 "has_template_vars": bool(variables), "template_vars": variables[:20]}
        if reference and len(reference) <= MAX_DRAFT_CHARS:
            draft["reference_output"] = reference
        drafts.append(draft)

    for path, rel in walk(root, stats):
        if not _is_prompt_source(rel):
            continue
        text = read_text(path, stats)
        if text is None:
            continue
        scanned += 1
        stem = path.name.split(".")[0]
        ext = path.suffix.lower()
        if ext == ".jsonl":
            for lineno, line in enumerate(text.splitlines(), 1):
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(record, dict):
                    inp, ref = _input_of(record)
                    if inp:
                        add(inp, ref, f"{rel}:{lineno}", f"{stem}-{lineno}")
        elif ext == ".json":
            try:
                value = json.loads(text)
            except json.JSONDecodeError:
                continue
            for index, record in enumerate(_records_from_json(value), 1):
                inp, ref = _input_of(record)
                if inp:
                    add(inp, ref, f"{rel}#{index}", f"{stem}-{index}")
        else:
            add(text, None, f"{rel}:1", stem)

    next_steps = ["Agree checks with the user for every draft: the drafts have empty 'checks' on purpose.",
                  "Fill or remove template variables before running."]
    if excluded_count:
        next_steps.append(f"{excluded_count} candidate example(s) were dropped because they contained personal "
                          "data or secrets; replace them with redacted or synthetic versions if needed.")
    return {
        "root": str(root),
        "files_scanned": scanned,
        "skipped": {k: v for k, v in stats.items() if k != "truncated"},
        "truncated": bool(stats.get("truncated")),
        "pagination": {"total": total_clean, "count": len(drafts), "offset": offset,
                       "has_more": offset + len(drafts) < total_clean,
                       "next_offset": offset + len(drafts) if offset + len(drafts) < total_clean else None},
        "drafts": drafts,
        "excluded": {"examples": excluded_count, "categories": excluded},
        "next_steps": next_steps,
    }


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    a = sub.add_parser("audit", help="list model IDs and AI SDKs")
    a.add_argument("path", nargs="?", default=".")
    e = sub.add_parser("examples", help="draft eval examples from prompt files and fixtures")
    e.add_argument("path", nargs="?", default=".")
    e.add_argument("--max", type=int, default=30)
    args = parser.parse_args(argv)
    root = Path(args.path)
    if not root.is_dir():
        print(f"Not a directory: {root}", file=sys.stderr)
        return 2
    try:
        result = audit_models(root) if args.command == "audit" else extract_examples(root, args.max)
    except core.ConfigError as exc:
        print(f"Input error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
