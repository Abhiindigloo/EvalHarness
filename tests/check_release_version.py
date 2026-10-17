#!/usr/bin/env python3
"""Fail unless every version field in the repository equals the given version (used by the release workflow)."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Dict

ROOT = Path(__file__).resolve().parents[1]


def collect_versions() -> Dict[str, str]:
    """Return {location: version} for every place a release version is recorded."""
    found: Dict[str, str] = {}
    for rel in (".claude-plugin/plugin.json", ".codex-plugin/plugin.json", ".cursor-plugin/plugin.json",
                "gemini-extension.json", "plugin.json", "server.json"):
        found[rel] = json.loads((ROOT / rel).read_text(encoding="utf-8"))["version"]
    found["marketplace.json plugin"] = json.loads(
        (ROOT / ".claude-plugin/marketplace.json").read_text(encoding="utf-8"))["plugins"][0]["version"]
    for i, pkg in enumerate(json.loads((ROOT / "server.json").read_text(encoding="utf-8"))["packages"]):
        found[f"server.json packages[{i}]"] = pkg["version"]
    server = re.search(r'^SERVER_VERSION = "([^"]+)"', (ROOT / "mcp/server.py").read_text(encoding="utf-8"), re.M)
    pyproject = re.search(r'^version = "([^"]+)"', (ROOT / "pyproject.toml").read_text(encoding="utf-8"), re.M)
    found["mcp/server.py"] = server.group(1) if server else "missing"
    found["pyproject.toml"] = pyproject.group(1) if pyproject else "missing"
    return found


def main(argv: list) -> int:
    expected = argv[1] if len(argv) > 1 else None
    versions = collect_versions()
    target = expected or versions["mcp/server.py"]
    wrong = {k: v for k, v in versions.items() if v != target}
    if wrong:
        print(f"Version mismatch (expected {target}): {wrong}", file=sys.stderr)
        return 1
    print(f"All {len(versions)} version fields are {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
