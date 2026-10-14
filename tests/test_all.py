"""Model Finder test suite. Run: python3 -m unittest discover -s tests -v

End-to-end tests use a local mock server that imitates the OpenAI-compatible,
Anthropic Messages, and Gemini generateContent response shapes. No real
provider is called and no real key is needed.
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import re
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / "skills"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(path.parent))
    sys.modules[name] = module
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


core = _load("mf_core", SKILLS / "eval-models/scripts/mf_core.py")
evalmod = _load("eval_models", SKILLS / "eval-models/scripts/eval_models.py")
routemod = _load("make_routing", SKILLS / "route-models/scripts/make_routing.py")
memmod = _load("estimate_memory", SKILLS / "size-local-model/scripts/estimate_memory.py")

GOOD = '{"invoice": "INV-1", "total": 10}'
BAD = "I am not sure."
SECRET = "sk-test-SECRET-value-123"


class MockProvider(BaseHTTPRequestHandler):
    flaky_hits = 0
    seen_auth: list = []

    def log_message(self, *args):  # silence
        pass

    def _send(self, status: int, payload: dict, headers: dict = None):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        req = json.loads(self.rfile.read(length) or b"{}")
        MockProvider.seen_auth.append(self.headers.get("Authorization") or self.headers.get("x-api-key")
                                      or self.headers.get("x-goog-api-key"))
        if self.path == "/v1/chat/completions":
            model = req["model"]
            prompt = req["messages"][-1]["content"]
            if model == "redirect":
                self.send_response(302)
                self.send_header("Location", "https://example.com/steal")
                self.end_headers()
                return
            if model == "flaky":
                MockProvider.flaky_hits += 1
                if MockProvider.flaky_hits == 1:
                    return self._send(429, {"error": "slow down"}, {"Retry-After": "0"})
            text = BAD if (model == "cheap" and "hard" in prompt) else GOOD
            cached = 40 if model == "strong" else 0
            return self._send(200, {
                "choices": [{"message": {"content": text}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 100, "completion_tokens": 20,
                          "prompt_tokens_details": {"cached_tokens": cached}},
            })
        if self.path == "/v1/messages":
            assert self.headers.get("anthropic-version") == core.ANTHROPIC_VERSION
            return self._send(200, {
                "content": [{"type": "thinking", "thinking": "..."}, {"type": "text", "text": GOOD}],
                "usage": {"input_tokens": 100, "output_tokens": 20}, "stop_reason": "end_turn",
            })
        if re.match(r"^/v1beta/models/[^/]+:generateContent$", self.path):
            return self._send(200, {
                "candidates": [{"content": {"parts": [{"text": "plan", "thought": True}, {"text": GOOD}]},
                                "finishReason": "STOP"}],
                "usageMetadata": {"promptTokenCount": 100, "candidatesTokenCount": 20,
                                  "thoughtsTokenCount": 30},
            })
        self._send(404, {"error": "not found"})


class MockServer:
    def __enter__(self):
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), MockProvider)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        return self

    def __exit__(self, *exc):
        self.httpd.shutdown()
        self.httpd.server_close()


def price(inp: float, out: float, cached=None) -> dict:
    return {"input": inp, "output": out, "cached_input": cached,
            "source": "https://example.com/pricing", "checked": "2026-10-13"}


def run_quiet(func, args):
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        return func(args)


class ChecksTest(unittest.TestCase):
    def test_check_types(self):
        checks = core.validate_checks([
            {"type": "contains", "value": "inv-1", "ignore_case": True},
            {"type": "json_keys", "keys": ["invoice", "total"]},
            {"type": "regex", "pattern": r"INV-\d"},
            {"type": "not_contains", "value": "sorry"},
            {"type": "max_chars", "value": 100},
        ], "t")
        self.assertEqual(core.run_checks(GOOD, checks), [])
        self.assertEqual(core.run_checks("```json\n" + GOOD + "\n```", checks[1:2]), [])
        self.assertIn("not valid JSON", core.run_checks(BAD, checks[1:2]))
        self.assertEqual(len(core.run_checks("sorry " * 30, checks)), 5)

    def test_invalid_checks(self):
        for bad in ([], [{"type": "eval"}], [{"type": "regex", "pattern": "("}],
                    [{"type": "regex", "pattern": "a" * 501}], [{"type": "max_chars", "value": True}]):
            with self.assertRaises(core.ConfigError):
                core.validate_checks(bad, "t")


class ValidationTest(unittest.TestCase):
    base = {"id": "a", "provider": "openai", "model": "gpt-x", "api_key_env": "OPENAI_API_KEY"}

    def test_rejects_unsafe_config(self):
        cases = [
            {**self.base, "api_key": "sk-123"},
            {**self.base, "base_url": "http://evil.example.com"},
            {**self.base, "base_url": "https://user:pw@api.example.com"},
            {**self.base, "model": "bad model; rm -rf"},
            {**self.base, "api_key_env": "lower-case"},
            {**self.base, "price_per_million": {"input": 1, "output": 2}},  # no source/date
            {**self.base, "price_per_million": {"input": float("inf"), "output": 2,
                                                "source": "x", "checked": "y"}},
            {"id": "b", "provider": "openai_compatible", "model": "m"},  # no base_url
        ]
        for case in cases:
            with self.assertRaises(core.ConfigError, msg=case):
                core.validate_candidate(case, 0)

    def test_allows_loopback_http(self):
        cand = core.validate_candidate({"id": "local", "provider": "openai_compatible", "model": "llama3",
                                        "base_url": "http://localhost:11434/"}, 0)
        self.assertEqual(cand.base_url, "http://localhost:11434")


class CostTest(unittest.TestCase):
    def test_unknown_is_not_zero(self):
        self.assertIsNone(core.compute_cost(core.Usage(100, 0, 20), None))
        self.assertIsNone(core.compute_cost(core.Usage(None, 0, None), core.Price(1, 2, None, "s", "d")))

    def test_cached_tokens_not_double_counted(self):
        p = core.Price(input=2.0, output=10.0, cached_input=0.5, source="s", checked="d")
        cost = core.compute_cost(core.Usage(uncached_input=60, cached_input=40, output=20), p)
        self.assertAlmostEqual(cost, (60 * 2 + 40 * 0.5 + 20 * 10) / 1e6)


class EndToEndTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        MockProvider.flaky_hits = 0
        MockProvider.seen_auth = []
        os.environ.update({"MF_TEST_KEY": SECRET, "MF_ANTHROPIC_KEY": SECRET, "MF_GEMINI_KEY": SECRET})

    def _config(self, url: str) -> Path:
        cfg = {
            "task": "Extract invoice id and total as JSON",
            "settings": {"max_output_tokens": 256, "temperature": 0, "timeout_s": 10},
            "pass_threshold": 0.5,
            "candidates": [
                {"id": "strong", "provider": "openai_compatible", "model": "strong", "base_url": url,
                 "api_key_env": "MF_TEST_KEY", "price_per_million": price(5, 20, 1)},
                {"id": "cheap", "provider": "openai_compatible", "model": "cheap", "base_url": url,
                 "api_key_env": "MF_TEST_KEY", "price_per_million": price(0.1, 0.4)},
                {"id": "claude", "provider": "anthropic", "model": "claude-test", "base_url": url,
                 "api_key_env": "MF_ANTHROPIC_KEY", "price_per_million": None},
                {"id": "gem", "provider": "gemini", "model": "gemini-test", "base_url": url,
                 "api_key_env": "MF_GEMINI_KEY", "price_per_million": price(1, 4)},
            ],
            "examples": [
                {"id": "easy", "input": "easy invoice", "checks": [
                    {"type": "json_keys", "keys": ["invoice", "total"]}, {"type": "contains", "value": "INV-1"}]},
                {"id": "hard", "input": "hard invoice", "checks": [
                    {"type": "json_keys", "keys": ["invoice", "total"]}]},
            ],
        }
        path = self.tmp / "config.json"
        path.write_text(json.dumps(cfg))
        return path

    def test_eval_route_and_router(self):
        with MockServer() as srv:
            cfg = self._config(srv.url)
            out = self.tmp / "results"
            self.assertEqual(run_quiet(evalmod.main, [str(cfg), "--out", str(out)]), 0)
            results = json.loads((out / "results.json").read_text())
            rows = {r["id"]: r for r in results["summary"]}
            self.assertEqual(rows["cheap"]["pass_rate"], 0.5)
            self.assertEqual(rows["strong"]["pass_rate"], 1.0)
            self.assertEqual(results["recommendation"]["cheapest_passing"], "cheap")
            self.assertIn("claude", results["recommendation"]["passing_unknown_cost"])
            self.assertIsNone(rows["claude"]["total_cost_usd"])
            # Gemini thinking tokens are billed as output: (100*1 + 50*4)/1e6 per call.
            gem = [r for r in results["records"] if r["candidate"] == "gem"][0]
            self.assertEqual(gem["output_tokens"], 50)
            self.assertAlmostEqual(gem["cost_usd"], 300 / 1e6)
            # Cached tokens split out for the strong model.
            strong = [r for r in results["records"] if r["candidate"] == "strong"][0]
            self.assertEqual((strong["uncached_input_tokens"], strong["cached_input_tokens"]), (60, 40))
            # Anthropic thinking blocks are excluded from text.
            claude = [r for r in results["records"] if r["candidate"] == "claude"][0]
            self.assertEqual(claude["output"], GOOD)
            # Secrets never written to disk.
            for name in ("results.json", "summary.md"):
                self.assertNotIn(SECRET, (out / name).read_text())
            self.assertIn("Cheapest candidate meeting the threshold", (out / "summary.md").read_text())

            guards = self.tmp / "guards.json"
            guards.write_text(json.dumps({"checks": [{"type": "json_keys", "keys": ["invoice", "total"]}]}))
            rdir = self.tmp / "routing"
            self.assertEqual(run_quiet(routemod.main, ["--results", str(out / "results.json"),
                                                       "--out", str(rdir), "--guards", str(guards)]), 0)
            routing = json.loads((rdir / "routing.json").read_text())
            self.assertEqual([c["id"] for c in routing["chain"]], ["cheap", "gem"])  # strong is dominated by gem
            self.assertTrue(any("strong" in n for n in routing["notes"]))
            yaml_text = (rdir / "litellm.config.yaml").read_text()
            self.assertIn('fallbacks: [{"cheap": ["gem"]}]', yaml_text)
            self.assertIn('api_key: "os.environ/MF_TEST_KEY"', yaml_text)
            self.assertNotIn(SECRET, yaml_text + json.dumps(routing))

            router = _load("router", rdir / "router.py")
            plan = router.load_routing(str(rdir / "routing.json"))
            easy = router.route("easy invoice", plan)
            self.assertTrue(easy["ok"])
            self.assertEqual((easy["model_id"], easy["escalated"]), ("cheap", False))
            hard = router.route("hard invoice", plan)
            self.assertTrue(hard["ok"])
            self.assertEqual(hard["model_id"], "gem")
            self.assertTrue(hard["escalated"])
            self.assertIn("not valid JSON", hard["attempts"][0]["reason"])

    def test_retry_redirect_and_dry_run(self):
        with MockServer() as srv:
            settings = core.Settings(max_output_tokens=50, timeout_s=5)
            flaky = core.validate_candidate({"id": "f", "provider": "openai_compatible", "model": "flaky",
                                             "base_url": srv.url, "api_key_env": "MF_TEST_KEY"}, 0)
            self.assertEqual(core.call_model(flaky, "hi", settings).retries, 1)
            redir = core.validate_candidate({"id": "r", "provider": "openai_compatible", "model": "redirect",
                                             "base_url": srv.url, "api_key_env": "MF_TEST_KEY"}, 0)
            with self.assertRaises(core.ModelCallError) as ctx:
                core.call_model(redir, "hi", settings)
            self.assertIn("Refused", str(ctx.exception))
            calls_before = len(MockProvider.seen_auth)
            cfg = self._config(srv.url)
            os.environ.pop("MF_GEMINI_KEY")
            self.assertEqual(run_quiet(evalmod.main, [str(cfg), "--dry-run"]), 0)
            self.assertEqual(len(MockProvider.seen_auth), calls_before, "dry run made network calls")
            self.assertEqual(run_quiet(evalmod.main, [str(cfg), "--out", str(self.tmp / "x")]), 2)


class RankingTest(unittest.TestCase):
    def test_ranks_by_cost_per_pass_not_total(self):
        # 'flaky' spends less in total but passes far less often, so each accepted result costs more.
        rows = [
            {"id": "flaky", "meets_threshold": True, "cost_known": True, "pass_rate": 0.5,
             "total_cost_usd": 0.010, "cost_per_pass_usd": 0.010 / 5},
            {"id": "solid", "meets_threshold": True, "cost_known": True, "pass_rate": 1.0,
             "total_cost_usd": 0.015, "cost_per_pass_usd": 0.015 / 10},
        ]
        self.assertEqual(evalmod.recommend(rows)["cheapest_passing"], "solid")
        chain, dropped = routemod.build_chain({"summary": rows}, None, False)
        # solid is cheaper per pass AND more reliable, so flaky is dominated and dropped.
        self.assertEqual((chain, dropped), (["solid"], ["flaky"]))

    def test_cascade_keeps_cheap_then_more_reliable(self):
        rows = [
            {"id": "big", "meets_threshold": True, "cost_known": True, "pass_rate": 1.0,
             "total_cost_usd": 0.10, "cost_per_pass_usd": 0.01},
            {"id": "small", "meets_threshold": True, "cost_known": True, "pass_rate": 0.8,
             "total_cost_usd": 0.008, "cost_per_pass_usd": 0.001},
        ]
        self.assertEqual(routemod.build_chain({"summary": rows}, None, False), (["small", "big"], []))


def _valid_aadhaar() -> str:
    base = "23456789012"
    return next(base + d for d in "0123456789" if core.verhoeff_valid(base + d))


AADHAAR = _valid_aadhaar()
PERSONAL_TEXT = (f"Customer Raj, Aadhaar {AADHAAR[:4]} {AADHAAR[4:8]} {AADHAAR[8:]}, PAN ABCPE1234F, "
                 "card 4111 1111 1111 1111, raj.k@example.co.in, UPI raj.k@okaxis, mobile +91 98765 43210")
PERSONAL_VALUES = [AADHAAR[:4] + " " + AADHAAR[4:8], "ABCPE1234F", "4111 1111", "raj.k@example.co.in",
                   "raj.k@okaxis", "98765 43210"]


class SensitiveDataTest(unittest.TestCase):
    def test_detects_each_category_once(self):
        found = core.detect_sensitive(PERSONAL_TEXT)
        self.assertEqual(found, {"aadhaar": 1, "pan": 1, "payment_card": 1, "email": 1,
                                 "upi_id": 1, "indian_mobile": 1})
        self.assertEqual(core.detect_sensitive("key sk-ant-" + "x" * 30 + " and AKIAABCDEFGHIJKLMNOP"),
                         {"secret": 2})

    def test_checksums_reduce_false_positives(self):
        bad_aadhaar = AADHAAR[:11] + str((int(AADHAAR[11]) + 1) % 10)
        for text in (f"ref {bad_aadhaar}", "ref 4111 1111 1111 1112", "Invoice INV-1042 total 1,250.00",
                     "order 1234567890", "version 2.5.1", "date 2026-03-03"):
            self.assertEqual(core.detect_sensitive(text), {}, text)

    def _cfg(self, url: str, text: str) -> Path:
        cfg = {"settings": {"max_output_tokens": 50, "timeout_s": 5},
               "candidates": [{"id": "cheap", "provider": "openai_compatible", "model": "cheap",
                               "base_url": url, "api_key_env": "MF_TEST_KEY"}],
               "examples": [{"id": "e1", "input": text, "checks": [{"type": "contains", "value": "INV"}]}]}
        path = Path(tempfile.mkdtemp()) / "c.json"
        path.write_text(json.dumps(cfg))
        return path

    def test_eval_blocks_personal_data_and_secrets(self):
        os.environ["MF_TEST_KEY"] = SECRET
        with MockServer() as srv:
            before = len(MockProvider.seen_auth)
            personal = self._cfg(srv.url, PERSONAL_TEXT)
            out = io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
                self.assertEqual(evalmod.main([str(personal), "--out", str(Path(tempfile.mkdtemp()))]), 2)
                self.assertEqual(evalmod.main([str(personal), "--dry-run"]), 0)
            secret = self._cfg(srv.url, "use key sk-proj-" + "y" * 30)
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
                self.assertEqual(evalmod.main([str(secret), "--allow-personal-data",
                                               "--out", str(Path(tempfile.mkdtemp()))]), 2)
            self.assertEqual(len(MockProvider.seen_auth), before, "blocked run reached the provider")
            printed = out.getvalue()
            for value in PERSONAL_VALUES + ["y" * 30]:
                self.assertNotIn(value, printed, "guard echoed a sensitive value")
            self.assertIn("aadhaar", printed)

            res = Path(tempfile.mkdtemp())
            self.assertEqual(run_quiet(evalmod.main, [str(personal), "--allow-personal-data",
                                                      "--out", str(res)]), 0)
            data = json.loads((res / "results.json").read_text())
            self.assertTrue(data["data_protection"]["personal_data_allowed"])
            self.assertFalse(data["data_protection"]["outputs_saved"])
            self.assertNotIn("output", data["records"][0])
            files = (res / "results.json").read_text() + (res / "summary.md").read_text()
            for value in PERSONAL_VALUES:
                self.assertNotIn(value, files)
            self.assertIn("## Data protection", (res / "summary.md").read_text())

    def test_router_policy(self):
        os.environ["MF_TEST_KEY"] = SECRET
        with MockServer() as srv:
            sys.path.insert(0, str(SKILLS / "route-models/assets"))
            router = _load("router_policy", SKILLS / "route-models/assets/router.py")
            chain = [core.validate_candidate({"id": "cheap", "provider": "openai_compatible", "model": "cheap",
                                              "base_url": srv.url, "api_key_env": "MF_TEST_KEY"}, 0)]
            settings = core.Settings(max_output_tokens=50, timeout_s=5)
            before = len(MockProvider.seen_auth)
            blocked = router.route(PERSONAL_TEXT, {"chain": chain, "settings": settings, "guards": [],
                                                   "pii_policy": "block"})
            self.assertFalse(blocked["ok"])
            self.assertIn("nothing was sent", blocked["blocked"])
            self.assertEqual(len(MockProvider.seen_auth), before)
            warned = router.route(PERSONAL_TEXT, {"chain": chain, "settings": settings, "guards": [],
                                                  "pii_policy": "warn"})
            self.assertTrue(warned["ok"])
            self.assertEqual(warned["sensitive_data"]["aadhaar"], 1)
            self.assertNotIn("ABCPE1234F", json.dumps(warned["sensitive_data"]))
            with self.assertRaises(core.ConfigError):
                path = Path(tempfile.mkdtemp()) / "r.json"
                path.write_text(json.dumps({"schema": "model-finder-routing/1", "pii_policy": "maybe",
                                            "chain": [chain[0].public_dict()],
                                            "settings": {"max_output_tokens": 50}}))
                router.load_routing(str(path))


class MemoryTest(unittest.TestCase):
    def test_weights_match_website_formula(self):
        est = memmod.estimate(7, 16)
        self.assertAlmostEqual(est.weights_gib, 13.0385160446167, places=9)
        self.assertIsNone(est.kv_cache_gib)

    def test_kv_cache_gqa(self):
        # 32 layers, 8 KV heads, head_dim 128, fp16: 128 KiB/token; 8192 tokens = 1 GiB.
        est = memmod.estimate(8.03, 16, layers=32, kv_heads=8, head_dim=128, context=8192)
        self.assertAlmostEqual(est.kv_per_token_kib, 128.0)
        self.assertAlmostEqual(est.kv_cache_gib, 1.0)
        est4 = memmod.estimate(8.03, 16, layers=32, kv_heads=8, head_dim=128, context=8192,
                               concurrency=4, overhead_pct=10, available_gib=24)
        self.assertAlmostEqual(est4.kv_cache_gib, 4.0)
        self.assertAlmostEqual(est4.total_gib, (est4.weights_gib + 4.0) * 1.1)
        self.assertLess(est4.headroom_gib, 24)

    def test_rejects_partial_or_bad_input(self):
        for kwargs in ({"layers": 32}, {"context": 0, "layers": 1, "kv_heads": 1, "head_dim": 1}):
            with self.assertRaises(ValueError):
                memmod.estimate(7, 16, **kwargs)
        with self.assertRaises(ValueError):
            memmod.estimate(float("nan"), 16)


class PackagingTest(unittest.TestCase):
    def test_core_copies_identical(self):
        a = (SKILLS / "eval-models/scripts/mf_core.py").read_bytes()
        b = (SKILLS / "route-models/scripts/mf_core.py").read_bytes()
        self.assertEqual(a, b, "mf_core.py copies drifted; copy eval-models version to route-models")

    def test_skill_frontmatter(self):
        for skill in sorted(p for p in SKILLS.iterdir() if p.is_dir()):
            text = (skill / "SKILL.md").read_text()
            front = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
            self.assertIsNotNone(front, skill)
            self.assertRegex(front.group(1), rf"(?m)^name: {skill.name}$")
            desc = re.search(r"(?m)^description: (.+)$", front.group(1))
            self.assertTrue(desc and 50 < len(desc.group(1)) <= 1024, f"{skill.name} description length")
            self.assertLess(len(text.splitlines()), 500)

    def test_manifests_consistent(self):
        versions = set()
        for rel in (".claude-plugin/plugin.json", ".codex-plugin/plugin.json", ".cursor-plugin/plugin.json",
                    "gemini-extension.json", "plugin.json"):
            data = json.loads((ROOT / rel).read_text())
            self.assertEqual(data["name"], "model-finder", rel)
            versions.add(data["version"])
        self.assertEqual(len(versions), 1, f"version mismatch: {versions}")
        for rel in (".claude-plugin/marketplace.json", ".cursor-plugin/marketplace.json",
                    ".agents/plugins/marketplace.json"):
            self.assertEqual(json.loads((ROOT / rel).read_text())["plugins"][0]["name"], "model-finder")


if __name__ == "__main__":
    unittest.main()
