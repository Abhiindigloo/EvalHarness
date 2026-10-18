"""Tests for the local MCP server, repository scanners and v1.3 helpers.

Run: python3 -m unittest discover -s tests -v
The MCP server is started as a real subprocess and driven over stdio.
"""
from __future__ import annotations

import importlib.util
import json
import os
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / "skills"
SERVER = ROOT / "mcp" / "server.py"


def _load(name: str, path: Path):
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(path.parent))
    sys.modules[name] = module
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


core = _load("mf_core", SKILLS / "eval-models/scripts/mf_core.py")
evalmod = _load("eval_models", SKILLS / "eval-models/scripts/eval_models.py")
scan = _load("repo_scan", SKILLS / "eval-models/scripts/repo_scan.py")
routemod = _load("make_routing", SKILLS / "route-models/scripts/make_routing.py")

FAKE_SECRET = "sk-ant-" + "Z" * 30
EXPECTED_TOOLS = {"modelfinder_" + n for n in (
    "audit_models", "draft_eval_examples", "create_eval_config", "validate_eval_config", "check_output",
    "rank_eval_results", "generate_routing", "estimate_cost", "estimate_memory", "scan_sensitive_data")}


def make_repo(base: Path) -> Path:
    """A small repository with models, SDKs, prompts, secrets and noise."""
    (base / "app").mkdir(parents=True)
    (base / "prompts").mkdir()
    (base / "evals").mkdir()
    (base / "node_modules" / "pkg").mkdir(parents=True)
    (base / "app" / "llm.py").write_text(
        "import os\nimport anthropic\nfrom openai import OpenAI\n"
        'MODEL = os.environ.get("MODEL", "claude-sonnet-4-5")\n'
        'FALLBACK = "gpt-4o-mini"\n'
        'BEDROCK = "bedrock/us.anthropic.claude-3-5-haiku-20241022-v1:0"\n'
        'ALIAS = "claude-3-7-sonnet-latest"\n'
        f'KEY = "{FAKE_SECRET}"  # must never appear in output\n'
        'print("a claude-friend wrote this")\n')
    (base / "app" / "index.ts").write_text('import Anthropic from "@anthropic-ai/sdk";\nconst m = "gemini-2.5-flash";\n')
    (base / "app" / "tokenizer.py").write_text('M = "o3-mini"\n')
    (base / "package.json").write_text('{"dependencies": {"openai": "^4", "react": "18"}}')
    (base / "requirements.txt").write_text("anthropic>=0.40\nrequests\n")
    (base / ".env").write_text('MODEL="gpt-5"\n')
    (base / "credentials.json").write_text('{"model": "gpt-4.1"}')
    (base / "node_modules" / "pkg" / "a.js").write_text('"gpt-4o"')
    (base / "prompts" / "summarize.prompt.md").write_text("Summarize this ticket: {ticket}\n")
    (base / "prompts" / "README.md").write_text("Docs, not a prompt.\n")
    (base / "evals" / "cases.jsonl").write_text(
        '{"input": "Classify: please refund my order", "expected": "refund"}\n'
        '{"input": "Write to me at someone@example.com"}\n'
        '{"messages": [{"role": "system", "content": "x"}, {"role": "user", "content": "Translate hello to Hindi"}]}\n'
        '{"input": "Classify: please refund my order"}\n')
    return base


class StdioClient:
    def __init__(self, cwd: Path, env: dict = None):
        full_env = {k: v for k, v in os.environ.items() if k != "MODEL_FINDER_ROOT"}
        full_env.update(env or {})
        self.proc = subprocess.Popen([sys.executable, "-I", str(SERVER)], cwd=str(cwd), env=full_env,
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.lines: "queue.Queue[bytes]" = queue.Queue()
        threading.Thread(target=self._pump, daemon=True).start()
        self.next_id = 0

    def _pump(self):
        for line in self.proc.stdout:
            self.lines.put(line)

    def send(self, msg) -> None:
        raw = msg if isinstance(msg, bytes) else json.dumps(msg).encode()
        self.proc.stdin.write(raw + b"\n")
        self.proc.stdin.flush()

    def recv(self, timeout: float = 10.0) -> dict:
        return json.loads(self.lines.get(timeout=timeout))

    def request(self, method: str, params: dict = None) -> dict:
        self.next_id += 1
        self.send({"jsonrpc": "2.0", "id": self.next_id, "method": method, "params": params or {}})
        reply = self.recv()
        assert reply.get("id") == self.next_id, reply
        return reply

    def initialize(self, version: str = "2025-06-18", roots: bool = False) -> dict:
        caps = {"roots": {"listChanged": True}} if roots else {}
        reply = self.request("initialize", {"protocolVersion": version, "capabilities": caps,
                                            "clientInfo": {"name": "test", "version": "0"}})
        self.send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        return reply["result"]

    def call(self, name: str, args: dict) -> dict:
        return self.request("tools/call", {"name": name, "arguments": args})["result"]

    def close(self):
        self.proc.stdin.close()
        self.proc.wait(timeout=10)
        self.proc.stdout.close()
        self.proc.stderr.close()


def result_json(result: dict) -> dict:
    """The full result: structuredContent on modern protocols (the text part is markdown by default)."""
    assert not result["isError"], result["content"][0]["text"]
    return result["structuredContent"]


def sample_results() -> dict:
    cand = lambda cid, model, p: {"id": cid, "provider": "openai_compatible", "model": model,
                                  "api_key_env": "MF_KEY", "base_url": "https://api.example.com",
                                  "price_per_million": {"input": p, "output": p * 4,
                                                        "source": "https://example.com/pricing",
                                                        "checked": "2026-10-14"}}
    row = lambda cid, rate, cpp: {"id": cid, "model": cid, "provider": "openai_compatible", "calls": 10,
                                  "passed": int(rate * 10), "errors": 0, "pass_rate": rate,
                                  "meets_threshold": rate >= 0.8, "median_latency_ms": 100, "p95_latency_ms": 200,
                                  "total_cost_usd": cpp * rate * 10, "cost_per_pass_usd": cpp, "cost_known": True}
    return {"schema": "model-finder-eval/1", "started_utc": "2026-10-14T00:00:00Z",
            "settings": {"max_output_tokens": 256, "timeout_s": 30, "temperature": 0, "system": None},
            "candidates": [cand("small", "small-1", 0.1), cand("big", "big-1", 3.0), cand("mid", "mid-1", 1.0)],
            "summary": [row("small", 0.8, 0.001), row("big", 1.0, 0.03), row("mid", 0.8, 0.01)],
            "data_protection": {"personal_data_detected": {}, "outputs_saved": True}}


class McpProtocolTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.repo = make_repo(self.tmp / "repo")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_handshake_and_catalog(self):
        c = StdioClient(self.repo)
        try:
            init = c.initialize("2025-06-18")
            self.assertEqual(init["protocolVersion"], "2025-06-18")
            manifest_version = json.loads((ROOT / ".claude-plugin/plugin.json").read_text())["version"]
            self.assertEqual(init["serverInfo"], {"name": "model_finder_mcp", "title": "Model Finder",
                                                 "version": manifest_version})
            self.assertIn("tools", init["capabilities"])
            self.assertTrue(init["instructions"])
            tools = c.request("tools/list")["result"]["tools"]
            self.assertEqual({t["name"] for t in tools}, EXPECTED_TOOLS)
            for t in tools:
                self.assertEqual(t["inputSchema"]["type"], "object", t["name"])
                self.assertTrue(t["annotations"]["readOnlyHint"], t["name"])
                self.assertFalse(t["annotations"]["openWorldHint"], t["name"])
                self.assertTrue(t["title"])
            self.assertEqual(c.request("ping")["result"], {})
        finally:
            c.close()

    def test_version_negotiation(self):
        c = StdioClient(self.repo)
        try:
            self.assertEqual(c.initialize("2024-11-05")["protocolVersion"], "2024-11-05")
            res = c.call("modelfinder_scan_sensitive_data", {"text": "hello", "response_format": "json"})
            self.assertNotIn("structuredContent", res)
            self.assertTrue(json.loads(res["content"][0]["text"])["clean"])
            tools = c.request("tools/list")["result"]["tools"]
            self.assertNotIn("title", tools[0])
            self.assertNotIn("outputSchema", tools[0])
        finally:
            c.close()
        c = StdioClient(self.repo)
        try:
            self.assertEqual(c.initialize("1999-01-01")["protocolVersion"], "2025-11-25")
        finally:
            c.close()

    def test_errors_and_notifications(self):
        c = StdioClient(self.repo)
        try:
            c.initialize()
            self.assertEqual(c.request("tools/call", {"name": "nope"})["error"]["code"], -32602)
            self.assertEqual(c.request("resources/list")["error"]["code"], -32601)
            bad = c.call("modelfinder_estimate_memory", {"params_b": 7})
            self.assertTrue(bad["isError"])
            self.assertIn("bits", bad["content"][0]["text"])
            self.assertTrue(c.call("modelfinder_estimate_memory", {"params_b": "7", "bits": 16})["isError"])
            c.send(b"this is not json")
            self.assertEqual(c.recv()["error"]["code"], -32700)
            c.send({"jsonrpc": "1.0", "id": 99, "method": "ping"})
            self.assertEqual(c.recv()["error"]["code"], -32600)
            c.send({"jsonrpc": "2.0", "method": "notifications/cancelled", "params": {}})
            self.assertEqual(c.request("ping")["result"], {})  # notification produced no reply
        finally:
            c.close()

    def test_client_roots_define_workspace(self):
        elsewhere = self.tmp / "elsewhere"
        elsewhere.mkdir()
        c = StdioClient(elsewhere)
        try:
            c.initialize(roots=True)
            req = c.recv()
            self.assertEqual(req["method"], "roots/list")
            c.send({"jsonrpc": "2.0", "id": req["id"], "result": {"roots": [{"uri": self.repo.resolve().as_uri()}]}})
            audit = result_json(c.call("modelfinder_audit_models", {}))
            self.assertEqual(Path(audit["root"]), self.repo.resolve())
            outside = c.call("modelfinder_audit_models", {"path": str(elsewhere)})
            self.assertTrue(outside["isError"])
            self.assertIn("inside the workspace", outside["content"][0]["text"])
            traversal = c.call("modelfinder_audit_models", {"path": "../elsewhere"})
            self.assertTrue(traversal["isError"])
        finally:
            c.close()

    def test_refuses_broad_workspace_and_ignores_placeholder_env(self):
        c = StdioClient(Path("/"), {"MODEL_FINDER_ROOT": "${workspacePath}"})
        try:
            c.initialize()
            res = c.call("modelfinder_audit_models", {})
            self.assertTrue(res["isError"])
            self.assertIn("too broad", res["content"][0]["text"])
        finally:
            c.close()
        c = StdioClient(self.tmp, {"MODEL_FINDER_ROOT": str(self.repo)})
        try:
            c.initialize()
            self.assertEqual(Path(result_json(c.call("modelfinder_audit_models", {}))["root"]), self.repo.resolve())
        finally:
            c.close()

    def test_started_in_plugin_folder_asks_for_project_path(self):
        """Agent Plugins hosts (Codex) start the server in the plugin root and pass no workspace."""
        c = StdioClient(ROOT)
        try:
            c.initialize()
            res = c.call("modelfinder_audit_models", {})
            self.assertTrue(res["isError"])
            self.assertIn("absolute path of the user's project", res["content"][0]["text"])
            self.assertTrue(c.call("modelfinder_audit_models", {"path": "skills"})["isError"])
            self.assertTrue(c.call("modelfinder_audit_models", {"path": str(ROOT)})["isError"])
            self.assertTrue(c.call("modelfinder_audit_models", {"path": "/"})["isError"])
            audit = result_json(c.call("modelfinder_audit_models", {"path": str(self.repo)}))
            self.assertEqual(Path(audit["root"]), self.repo.resolve())
            drafts = result_json(c.call("modelfinder_draft_eval_examples", {"path": str(self.repo)}))
            self.assertIn("pagination", drafts)
            self.assertFalse(c.call("modelfinder_estimate_memory", {"params_b": 7, "bits": 16})["isError"])
        finally:
            c.close()

    def test_internal_error_never_logs_arguments(self):
        """Directory policy: no extraneous data collection, even for logging. Only the error type is logged."""
        code = ("import sys, importlib.util, json\n"
                "spec = importlib.util.spec_from_file_location('srv', sys.argv[1])\n"
                "m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)\n"
                "def boom(args): raise RuntimeError('LEAK ' + json.dumps(args))\n"
                "[t.update(handler=boom) for t in m.TOOLS if t['name'] == 'modelfinder_scan_sensitive_data']\n"
                "sys.exit(m.main(['server']))\n")
        msgs = [{"jsonrpc": "2.0", "id": 1, "method": "initialize",
                 "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "0"}}},
                {"jsonrpc": "2.0", "method": "notifications/initialized"},
                {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                 "params": {"name": "modelfinder_scan_sensitive_data", "arguments": {"text": "secret-marker-xyz"}}}]
        proc = subprocess.run([sys.executable, "-I", "-c", code, str(SERVER)], cwd=str(self.repo),
                              input="\n".join(json.dumps(m) for m in msgs) + "\n",
                              capture_output=True, text=True, timeout=30)
        self.assertIn("RuntimeError", proc.stderr)
        for stream in (proc.stdout, proc.stderr):
            self.assertNotIn("secret-marker-xyz", stream)
            self.assertNotIn("LEAK", stream)
        reply = [json.loads(line) for line in proc.stdout.splitlines() if line.strip()][-1]["result"]
        self.assertTrue(reply["isError"])

    def test_every_tool(self):
        c = StdioClient(self.repo)
        try:
            c.initialize()
            audit = c.call("modelfinder_audit_models", {})
            self.assertIn("structuredContent", audit)
            ids = {m["id"] for m in result_json(audit)["models"]}
            self.assertIn("claude-sonnet-4-5", ids)

            drafts = result_json(c.call("modelfinder_draft_eval_examples", {"limit": 10}))
            self.assertEqual(drafts["excluded"]["categories"], {"email": 1})

            cost = result_json(c.call("modelfinder_estimate_cost", {
                "requests_per_month": 10000, "input_tokens": 1000, "output_tokens": 300,
                "input_price_per_million": 1.0, "output_price_per_million": 4.0, "pass_rate": 0.5}))
            self.assertAlmostEqual(cost["monthly_cost_usd"], 10000 * (1000 * 1 + 300 * 4) / 1e6)
            self.assertAlmostEqual(cost["cost_per_accepted_result_usd"], 2 * (1000 + 1200) / 1e6)

            mem = result_json(c.call("modelfinder_estimate_memory", {"params_b": 8.03, "bits": 16, "layers": 32, "kv_heads": 8,
                                                         "head_dim": 128, "context": 8192}))
            self.assertAlmostEqual(mem["kv_cache_gib"], 1.0)

            scan_res = c.call("modelfinder_scan_sensitive_data", {"text": f"mail me at a.b@example.com {FAKE_SECRET}"})
            body = scan_res["content"][0]["text"] + json.dumps(scan_res["structuredContent"])
            self.assertNotIn("a.b@example.com", body)
            self.assertNotIn(FAKE_SECRET, body)
            self.assertEqual(scan_res["structuredContent"]["secrets"], 1)

            chk = result_json(c.call("modelfinder_check_output", {"text": "not json", "checks": [{"type": "json_keys", "keys": ["a"]}]}))
            self.assertFalse(chk["passed"])

            cand = {"id": "c1", "provider": "anthropic", "model": "claude-test", "api_key_env": "ANTHROPIC_API_KEY",
                    "price_per_million": None}
            created = result_json(c.call("modelfinder_create_eval_config", {
                "task": "classify", "candidates": [cand],
                "examples": [{"id": "e1", "input": "Classify: refund", "checks": [{"type": "contains", "value": "refund"}]}]}))
            self.assertTrue(created["valid"], created.get("error"))
            self.assertEqual(created["required_env_vars"], ["ANTHROPIC_API_KEY"])
            self.assertEqual(created["unpriced_candidates"], ["c1"])
            self.assertEqual(created["data_protection"]["run_verdict"], "clear")

            cfg = dict(created["config"])
            cfg["examples"] = [{"id": "e2", "input": "Customer email raj@example.com wants a refund",
                                "checks": [{"type": "contains", "value": "refund"}]}]
            val = result_json(c.call("modelfinder_validate_eval_config", {"config": cfg}))
            self.assertTrue(val["valid"])
            self.assertTrue(val["data_protection"]["run_verdict"].startswith("blocked unless"))
            self.assertNotIn("raj@example.com", json.dumps(val))
            keyed = dict(cfg, candidates=[dict(cand, api_key="sk-123")])
            self.assertFalse(result_json(c.call("modelfinder_validate_eval_config", {"config": keyed}))["valid"])

            ranked = result_json(c.call("modelfinder_rank_eval_results", {"results": sample_results()}))
            self.assertEqual(ranked["recommendation"]["cheapest_passing"], "small")
            self.assertEqual(ranked["cascade"], ["small", "big"])
            self.assertEqual(ranked["dominated"], ["mid"])

            routing = result_json(c.call("modelfinder_generate_routing", {
                "results": sample_results(), "pii_policy": "block",
                "guards": [{"type": "max_chars", "value": 500}]}))
            self.assertEqual(routing["chain"], ["small", "big"])
            self.assertEqual(routing["routing_json"]["pii_policy"], "block")
            self.assertIn('fallbacks: [{"small": ["big"]}]', routing["litellm_config_yaml"])
            bad_policy = c.call("modelfinder_generate_routing", {"results": sample_results(), "pii_policy": "maybe"})
            self.assertTrue(bad_policy["isError"])
        finally:
            c.close()


    def test_builder_conventions(self):
        """Prefixed names, outputSchema, markdown default, JSON option, filters, pagination, strict arguments."""
        c = StdioClient(self.repo)
        try:
            c.initialize("2025-06-18")
            tools = {t["name"]: t for t in c.request("tools/list")["result"]["tools"]}
            for name, t in tools.items():
                self.assertTrue(name.startswith("modelfinder_"), name)
                self.assertIn("response_format", t["inputSchema"]["properties"], name)
                self.assertFalse(t["inputSchema"]["additionalProperties"], name)
                self.assertEqual(t["outputSchema"]["type"], "object", name)
                for prop, spec in t["inputSchema"]["properties"].items():
                    self.assertTrue(spec.get("description"), f"{name}.{prop} has no description")
            md = c.call("modelfinder_audit_models", {})
            self.assertTrue(md["content"][0]["text"].startswith("## AI models in"))
            for key in tools["modelfinder_audit_models"]["outputSchema"]["required"]:
                self.assertIn(key, md["structuredContent"])
            js = c.call("modelfinder_audit_models", {"response_format": "json"})
            self.assertEqual(json.loads(js["content"][0]["text"]), js["structuredContent"])
            page1 = result_json(c.call("modelfinder_audit_models", {"limit": 2}))
            self.assertEqual((page1["pagination"]["count"], page1["pagination"]["has_more"]), (2, True))
            page2 = result_json(c.call("modelfinder_audit_models", {"limit": 2, "offset": page1["pagination"]["next_offset"]}))
            self.assertFalse({m["id"] for m in page1["models"]} & {m["id"] for m in page2["models"]})
            total = page1["pagination"]["total"]
            self.assertEqual(page1["pagination"]["count"] + page2["pagination"]["count"] + max(0, total - 4), total)
            openai_only = result_json(c.call("modelfinder_audit_models", {"provider_family": "openai"}))
            self.assertTrue(openai_only["models"] and all(m["provider_family"] == "openai" for m in openai_only["models"]))
            hard = result_json(c.call("modelfinder_audit_models", {"hard_coded_only": True}))
            self.assertNotIn("claude-sonnet-4-5", {m["id"] for m in hard["models"]})
            for bad in ({"provider_family": "acme"}, {"limit": 0}, {"limit": 201}, {"offset": -1},
                        {"hard_coded_only": "yes"}, {"pathh": "app"}, {"response_format": "xml"}):
                res = c.call("modelfinder_audit_models", bad)
                self.assertTrue(res["isError"], bad)
                self.assertTrue(res["content"][0]["text"].startswith("Error: "), bad)
            cost = c.call("modelfinder_estimate_cost", {"requests_per_month": 100000, "input_tokens": 60,
                                                        "output_tokens": 8, "input_price_per_million": 0.25,
                                                        "output_price_per_million": 1.5, "pass_rate": 0.8})
            self.assertEqual(cost["structuredContent"]["monthly_cost_usd"], 2.7)
            self.assertIn("Monthly cost including retries: $3.38", cost["content"][0]["text"])
        finally:
            c.close()


class RepoScanTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.repo = make_repo(self.tmp / "repo")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_audit_inventory_and_privacy(self):
        outside = self.tmp / "outside"
        outside.mkdir()
        (outside / "x.py").write_text('M = "grok-4"\n')
        try:
            os.symlink(outside, self.repo / "linked", target_is_directory=True)
        except (OSError, NotImplementedError):
            pass
        audit = scan.audit_models(self.repo)
        text = json.dumps(audit)
        self.assertNotIn(FAKE_SECRET, text)
        models = {m["id"]: m for m in audit["models"]}
        self.assertEqual(set(models), {"claude-sonnet-4-5", "gpt-4o-mini", "claude-3-7-sonnet-latest", "o3-mini",
                                       "bedrock/us.anthropic.claude-3-5-haiku-20241022-v1:0", "gemini-2.5-flash"})
        self.assertNotIn("gpt-5", models)       # .env skipped
        self.assertNotIn("gpt-4.1", models)     # credentials.json skipped
        self.assertNotIn("gpt-4o", models)      # node_modules skipped
        self.assertNotIn("grok-4", models)      # symlink not followed
        self.assertEqual(models["claude-sonnet-4-5"]["used_as_env_default"], 1)
        self.assertEqual(models["claude-sonnet-4-5"]["notes"], [])
        self.assertTrue(any("latest" in n for n in models["claude-3-7-sonnet-latest"]["notes"]))
        self.assertTrue(any("Hard-coded" in n for n in models["gpt-4o-mini"]["notes"]))
        bedrock = models["bedrock/us.anthropic.claude-3-5-haiku-20241022-v1:0"]
        self.assertEqual((bedrock["routes"], bedrock["provider_family"]), (["AWS Bedrock"], "anthropic"))
        self.assertEqual(models["o3-mini"]["provider_family"], "openai")
        sdks = {s["name"]: s for s in audit["sdks"]}
        self.assertEqual(set(sdks), {"anthropic", "openai", "@anthropic-ai/sdk"})
        self.assertEqual(sdks["anthropic"]["found_as"], ["dependency", "python import"])
        self.assertGreaterEqual(audit["skipped"]["skipped_secret_like"], 2)
        for loc in (l for m in audit["models"] for l in m["locations"]):
            self.assertRegex(loc, r"^[\w./-]+:\d+$")

    def test_examples_drafting(self):
        out = scan.extract_examples(self.repo, 30)
        text = json.dumps(out)
        self.assertNotIn("someone@example.com", text)
        self.assertEqual(out["excluded"], {"examples": 1, "categories": {"email": 1}})
        drafts = {d["source"]: d for d in out["drafts"]}
        self.assertEqual(set(drafts), {"evals/cases.jsonl:1", "evals/cases.jsonl:3", "prompts/summarize.prompt.md:1"})
        self.assertEqual(drafts["evals/cases.jsonl:1"]["reference_output"], "refund")
        self.assertEqual(drafts["evals/cases.jsonl:3"]["input"], "Translate hello to Hindi")
        self.assertEqual(drafts["prompts/summarize.prompt.md:1"]["template_vars"], ["ticket"])
        self.assertTrue(all(d["checks"] == [] for d in out["drafts"]))
        self.assertEqual(len({d["id"] for d in out["drafts"]}), 3)
        capped = scan.extract_examples(self.repo, 1)
        self.assertEqual(len(capped["drafts"]), 1)
        self.assertEqual(capped["pagination"], {"total": 3, "count": 1, "offset": 0, "has_more": True, "next_offset": 1})
        page2 = scan.extract_examples(self.repo, 1, offset=1)
        self.assertEqual(page2["drafts"][0]["id"], out["drafts"][1]["id"])  # ids stable across pages
        last = scan.extract_examples(self.repo, 5, offset=2)
        self.assertEqual((len(last["drafts"]), last["pagination"]["has_more"]), (1, False))
        for bad in (0, 201, True, "3"):
            with self.assertRaises(core.ConfigError):
                scan.extract_examples(self.repo, bad)


class HelpersTest(unittest.TestCase):
    def test_monthly_cost(self):
        r = core.estimate_monthly_cost(1000, 2000, 500, 3.0, 15.0, cached_fraction=0.5, cached_input_price=0.3)
        per = (1000 * 3.0 + 1000 * 0.3 + 500 * 15.0) / 1e6
        self.assertAlmostEqual(r["cost_per_request_usd"], per)
        self.assertAlmostEqual(r["monthly_cost_usd"], per * 1000)
        with self.assertRaises(core.ConfigError):
            core.estimate_monthly_cost(1, 1, 1, 1, 1, cached_fraction=0.5)
        with self.assertRaises(core.ConfigError):
            core.estimate_monthly_cost(1, 1, 1, 1, 1, pass_rate=0)
        with self.assertRaises(core.ConfigError):
            core.estimate_monthly_cost(-1, 1, 1, 1, 1)

    def test_parse_config_and_placeholders(self):
        cfg = json.loads((SKILLS / "eval-models/assets/example-config.json").read_text())
        with self.assertRaises(core.ConfigError):
            evalmod.parse_config(cfg)
        with self.assertRaises(core.ConfigError):
            evalmod.parse_config([])

    def test_build_routing_function(self):
        routing, chain, yaml_text = routemod.build_routing(sample_results(), [], None, False, "warn")
        self.assertEqual([c.id for c in chain], ["small", "big"])
        self.assertEqual(routing["schema"], "model-finder-routing/1")
        self.assertIn("model_list:", yaml_text)
        with self.assertRaises(core.ConfigError):
            routemod.build_routing({"schema": "other"})


class McpPackagingTest(unittest.TestCase):
    def _expand(self, text: str, mapping: dict) -> str:
        for key, value in mapping.items():
            text = text.replace(key, value)
        return text

    def test_launch_configs_point_at_server(self):
        mcp = json.loads((ROOT / ".mcp.json").read_text())["mcpServers"]["model-finder"]
        # Claude directory rule: run a file in the plugin with plain arguments and a full ${CLAUDE_PLUGIN_ROOT} path.
        self.assertEqual(mcp["command"], "python3")
        self.assertEqual(mcp["args"], ["${CLAUDE_PLUGIN_ROOT}/mcp/server.py"])
        self.assertTrue(Path(self._expand(mcp["args"][0], {"${CLAUDE_PLUGIN_ROOT}": str(ROOT)})).is_file())
        for rel in (".claude-plugin/plugin.json", ".cursor-plugin/plugin.json", ".codex-plugin/plugin.json"):
            self.assertEqual(json.loads((ROOT / rel).read_text())["mcpServers"], "./.mcp.json", rel)
        # The root .mcp.json would also load as a project config for people working inside this repo: keep it off there.
        settings = json.loads((ROOT / ".claude/settings.json").read_text())
        self.assertIn("model-finder", settings["disabledMcpjsonServers"])
        gem = json.loads((ROOT / "gemini-extension.json").read_text())["mcpServers"]["model-finder"]
        path = self._expand(gem["args"][0], {"${extensionPath}": str(ROOT), "${/}": os.sep})
        self.assertTrue(Path(path).is_file())
        self.assertEqual(gem["env"]["MODEL_FINDER_ROOT"], "${workspacePath}")
        self.assertFalse((ROOT / "bin").exists(), "a top-level bin/ blocks installation in claude.ai and Cowork")

    def test_agent_plugins_mcp_json(self):
        """A root plugin.json makes Codex, Copilot CLI and Cursor load the Agent Plugins mcp.json (no dot).

        Cursor does not expand ${PLUGIN_ROOT} and Codex does not expand ${CLAUDE_PLUGIN_ROOT}, so the command is
        a plugin-relative ./ path with no variables, which the Agent Plugins spec resolves against the plugin root.
        """
        doc = json.loads((ROOT / "mcp.json").read_text())
        self.assertEqual(set(doc), {"$schema", "mcpServers"})
        server = doc["mcpServers"]["model-finder"]
        self.assertEqual(server, {"type": "stdio", "command": "./mcp/server.py"})
        self.assertNotIn("${", json.dumps(doc))
        self.assertTrue(SERVER.read_text().startswith("#!/usr/bin/env python3\n"))
        if os.name != "nt":
            self.assertTrue(os.access(SERVER, os.X_OK), "mcp/server.py must be executable (git mode 100755)")
        interface = json.loads((ROOT / "plugin.json").read_text())["extensions"]["com.openai"]["interface"]
        for rel in [interface["logo"], interface["composerIcon"],
                    *json.loads((ROOT / ".codex-plugin/plugin.json").read_text())["interface"].values()]:
            if isinstance(rel, str) and rel.endswith(".png"):
                self.assertTrue(rel.startswith("./"), f"{rel}: Codex ignores asset paths without ./")
                self.assertTrue((ROOT / rel).is_file(), rel)
        for prompt in interface["defaultPrompt"]:
            self.assertLessEqual(len(prompt), 128, "Codex ignores default prompts over 128 characters")

    def test_versions_license_and_listing_fields(self):
        server_version = None
        for line in SERVER.read_text().splitlines():
            if line.startswith("SERVER_VERSION"):
                server_version = line.split('"')[1]
        versions = {json.loads((ROOT / rel).read_text())["version"] for rel in (
            ".claude-plugin/plugin.json", ".codex-plugin/plugin.json", ".cursor-plugin/plugin.json",
            "gemini-extension.json", "plugin.json", "server.json")}
        versions.add(json.loads((ROOT / ".claude-plugin/marketplace.json").read_text())["plugins"][0]["version"])
        self.assertEqual(versions, {server_version})
        checker = subprocess.run([sys.executable, str(ROOT / "tests/check_release_version.py"), server_version],
                                 capture_output=True, text=True)
        self.assertEqual(checker.returncode, 0, checker.stderr)
        self.assertIn(f"## {server_version}", (ROOT / "CHANGELOG.md").read_text())
        self.assertTrue((ROOT / "LICENSE").read_text().startswith("MIT License"))
        claude = json.loads((ROOT / ".claude-plugin/plugin.json").read_text())
        self.assertEqual(claude["license"], "MIT")
        self.assertTrue((ROOT / claude["icon"]).is_file())

    def test_no_dependency_on_old_website(self):
        for path in ROOT.rglob("*"):
            if path.is_file() and ".git" not in path.parts and "__pycache__" not in path.parts \
                    and path.suffix in (".md", ".json", ".py", ".yml", ".yaml", ".txt") and path.name != "CHANGELOG.md":
                text = path.read_text(encoding="utf-8", errors="replace")
                for old in ("modelfinder-" + "website", "abhiindigloo." + "github.io"):
                    self.assertNotIn(old, text.lower(), f"{path.relative_to(ROOT)} still references {old}")

    def test_listing_links_point_to_files_in_this_repo(self):
        repo = "https://github.com/Abhiindigloo/EvalHarness/blob/main/"
        codex = json.loads((ROOT / ".codex-plugin/plugin.json").read_text())["interface"]
        links = [codex[k] for k in ("supportURL", "privacyPolicyURL", "termsOfServiceURL")]
        for link in links:
            self.assertTrue(link.startswith(repo), link)
            self.assertTrue((ROOT / link[len(repo):]).is_file(), f"{link} points to a missing file")

    def test_registry_and_pypi_metadata(self):
        """server.json (MCP Registry), pyproject.toml (PyPI) and the README ownership marker agree."""
        reg = json.loads((ROOT / "server.json").read_text())
        self.assertEqual(reg["name"], "co.indigloo/model-finder")  # verified by a DNS TXT record on indigloo.co
        self.assertLessEqual(len(reg["description"]), 100)
        pkg = reg["packages"][0]
        self.assertEqual((pkg["registryType"], pkg["identifier"], pkg["transport"]["type"]),
                         ("pypi", "model-finder-mcp", "stdio"))
        self.assertIn(f"mcp-name: {reg['name']}", (ROOT / "README.md").read_text())
        pyproject = (ROOT / "pyproject.toml").read_text()
        self.assertIn('name = "model-finder-mcp"', pyproject)
        self.assertIn('model-finder-mcp = "model_finder_mcp.server:main"', pyproject)
        self.assertIn("dependencies = []", pyproject)
        glama = json.loads((ROOT / "glama.json").read_text())
        self.assertEqual(glama["maintainers"], ["Abhiindigloo"])

    def test_cursor_install_link_runs_the_pypi_package(self):
        """The README's one-click Cursor link must not depend on ${CLAUDE_PLUGIN_ROOT}, which only plugin installs set."""
        import base64
        import re
        import urllib.parse
        readme = (ROOT / "README.md").read_text()
        encoded = re.findall(r"https://cursor\.com/en/install-mcp\?name=model-finder&config=([A-Za-z0-9%+/=]+)\)", readme)
        self.assertEqual(len(encoded), 1, "expected exactly one Cursor install link in README.md")
        config = json.loads(base64.b64decode(urllib.parse.unquote(encoded[0])))
        version = json.loads((ROOT / "server.json").read_text())["version"]
        self.assertEqual(config["command"], "uvx")
        self.assertEqual(config["args"], [f"model-finder-mcp=={version}"])
        self.assertEqual(config["env"], {"MODEL_FINDER_ROOT": "${workspaceFolder}"})
        self.assertNotIn("PLUGIN_ROOT", json.dumps(config))

    def test_server_runs_from_the_wheel_layout(self):
        """The PyPI wheel puts server.py and skills/ side by side in model_finder_mcp/; the server must find them."""
        tmp = Path(tempfile.mkdtemp())
        try:
            pkg = tmp / "model_finder_mcp"
            pkg.mkdir()
            shutil.copy(SERVER, pkg / "server.py")
            shutil.copytree(SKILLS, pkg / "skills")
            (pkg / "__init__.py").write_text("")
            out = subprocess.run([sys.executable, "-I", "-c",
                                  "import sys; sys.path.insert(0, sys.argv[1]); "
                                  "from model_finder_mcp.server import main; sys.argv = ['x', '--version']; "
                                  "raise SystemExit(main())", str(tmp)],
                                 capture_output=True, text=True, timeout=30)
            self.assertEqual(out.returncode, 0, out.stderr)
            self.assertIn("model_finder_mcp", out.stdout)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_policies_are_final_and_complete(self):
        """Listing pages: privacy (collection, use, retention), terms, security reporting; no draft markers."""
        privacy = (ROOT / "PRIVACY.md").read_text()
        terms = (ROOT / "TERMS.md").read_text()
        security = (ROOT / "SECURITY.md").read_text()
        for doc, name in ((privacy, "PRIVACY"), (terms, "TERMS")):
            self.assertNotIn("Draft", doc, name)
            self.assertIn("Effective date:", doc, name)
            self.assertIn("Indigloo Softwares Private Limited", doc, name)
        for heading in ("What the software processes", "What Indigloo collects", "Children", "Contact", "Changes"):
            self.assertIn(heading, privacy)
        self.assertIn("Retained by Indigloo", privacy)
        for heading in ("No warranty", "Limitation of liability", "Governing law"):
            self.assertIn(heading, terms)
        for heading in ("Supported versions", "Reporting a vulnerability", "In scope", "Security design"):
            self.assertIn(heading, security)

    def test_every_repo_link_uses_the_real_repo_name(self):
        """The GitHub repo is Abhiindigloo/EvalHarness; a misspelt name breaks every install command."""
        import re
        pattern = re.compile(r"(?<!io\.github\.)abhiindigloo/([A-Za-z0-9_.-]+)", re.I)  # registry names are io.github.<owner>/<server>
        for path in ROOT.rglob("*"):
            if path.is_file() and ".git" not in path.parts and "__pycache__" not in path.parts \
                    and path.suffix in (".md", ".json", ".py") and path.name != "CHANGELOG.md" and path != Path(__file__):
                for name in pattern.findall(path.read_text(encoding="utf-8", errors="replace")):
                    self.assertEqual(name.lower().removesuffix(".git"), "evalharness", f"{path.relative_to(ROOT)}: {name}")

    def test_server_and_scanner_make_no_network_calls(self):
        for path in (SERVER, SKILLS / "eval-models/scripts/repo_scan.py"):
            source = path.read_text()
            for forbidden in ("call_model", "_post_json", "urlopen", "import socket", "http.client", "import requests"):
                self.assertNotIn(forbidden, source, f"{path.name} references {forbidden}")


if __name__ == "__main__":
    unittest.main()
