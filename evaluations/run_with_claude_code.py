#!/usr/bin/env python3
"""Run model_finder_eval.xml through headless Claude Code, limited to the Model Finder MCP tools.

Usage: python3 evaluations/run_with_claude_code.py [OUT_DIR]

Requires the `claude` CLI, signed in. Each question runs in evaluations/fixture-repo with the plugin loaded
from this repository; built-in file, shell and web tools are denied so only the MCP tools can answer.
Writes one JSON record per question to OUT_DIR (default: evaluations/results) and prints the score.
"""
import json, os, re, subprocess, sys, xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
HERE = Path(__file__).resolve().parent
PLUGIN = str(HERE.parent); FIX = str(HERE / "fixture-repo")
OUT = sys.argv[1] if len(sys.argv) > 1 else str(HERE / "results")
os.makedirs(OUT, exist_ok=True)
pairs = [(q.find("question").text.strip(), q.find("answer").text.strip())
         for q in ET.parse(str(HERE / "model_finder_eval.xml")).getroot().findall("qa_pair")]
# Some hosted environments disable plugin MCP servers with this variable; the evaluation needs them.
env = {k: v for k, v in os.environ.items() if k != "CLAUDE_CODE_SKIP_PLUGIN_MCP_SERVERS"}
DENY = "Bash,Read,Glob,Grep,Edit,Write,NotebookEdit,WebFetch,WebSearch,Task,Agent,Skill"
def run(idx):
    q, expected = pairs[idx]
    prompt = (q + "\n\nUse only the model-finder MCP tools available to you. When done, reply with the final value "
              "only, inside <answer></answer> tags.")
    r = subprocess.run(["claude", "-p", prompt, "--plugin-dir", PLUGIN, "--output-format", "stream-json", "--verbose",
                        "--max-turns", "20", "--allowedTools", "mcp__plugin_model-finder_model-finder",
                        "--disallowedTools", DENY], cwd=FIX, env=env, capture_output=True, text=True, timeout=420)
    calls, final = [], ""
    for line in r.stdout.splitlines():
        try: e = json.loads(line)
        except Exception: continue
        if e.get("type") == "assistant":
            calls += [b["name"].split("__")[-1] for b in e["message"]["content"] if b.get("type") == "tool_use"]
        if e.get("type") == "result": final = e.get("result", "")
    m = re.search(r"<answer>\s*(.*?)\s*</answer>", final, re.S)
    got = m.group(1).strip() if m else final.strip()[:80]
    norm = lambda s: s.strip().strip("`$ ").lower()
    rec = {"q": idx + 1, "expected": expected, "got": got, "correct": norm(got) == norm(expected),
           "tool_calls": [c for c in calls if c != "ToolSearch"], "final": final[-600:]}
    open(f"{OUT}/q{idx+1}.json", "w").write(json.dumps(rec, indent=1))
    return rec
with ThreadPoolExecutor(5) as ex:
    recs = list(ex.map(run, range(len(pairs))))
for r in recs:
    print(f"Q{r['q']:<2} {'PASS' if r['correct'] else 'FAIL'}  expected={r['expected']!r:<16} got={r['got']!r:<18} tools={r['tool_calls']}")
print("score", sum(r["correct"] for r in recs), "/", len(recs))
