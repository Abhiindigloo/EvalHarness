"""Model Finder core: provider clients, deterministic checks, cost math.

Standard library only (Python 3.9+), so nothing extra is installed.
Security properties:
  * API keys are read from environment variables named in the config; a key
    value is never accepted from the config, printed, or written to disk.
  * Remote endpoints must use HTTPS; plain HTTP is allowed only for loopback
    hosts (local runtimes such as Ollama or vLLM).
  * HTTP redirects are refused so credentials cannot be forwarded elsewhere.
  * Response bodies, regex patterns, and inputs are size-capped.

This file is intentionally duplicated in skills/route-models/scripts/ so each
skill works when installed on its own. the test suite fails if the two
copies drift apart (see tests/test_all.py).
"""
from __future__ import annotations

import ipaddress
import json
import math
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

PROVIDERS = ("anthropic", "openai", "gemini", "openai_compatible")
DEFAULT_BASE_URLS = {
    "anthropic": "https://api.anthropic.com",
    "openai": "https://api.openai.com",
    "gemini": "https://generativelanguage.googleapis.com",
}
ANTHROPIC_VERSION = "2023-06-01"
CHECK_TYPES = ("contains", "not_contains", "exact", "regex", "json_keys", "max_chars")

MAX_RESPONSE_BYTES = 10 * 1024 * 1024
MAX_PATTERN_CHARS = 500
MAX_REGEX_SUBJECT_CHARS = 100_000
MAX_OUTPUT_TOKENS = 64_000
MAX_RETRIES = 2
MAX_RETRY_WAIT_S = 30.0

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_MODEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,199}$")
_ENV_RE = re.compile(r"^[A-Z_][A-Z0-9_]{0,127}$")


class ConfigError(ValueError):
    """Raised for invalid configuration. Messages never include secrets."""


class ModelCallError(RuntimeError):
    """Raised when a provider call fails after retries."""


# --------------------------------------------------------------------------
# Data types
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class Price:
    """USD per million tokens, from a verified official source."""

    input: float
    output: float
    cached_input: Optional[float] = None
    source: str = ""
    checked: str = ""


@dataclass(frozen=True)
class Candidate:
    id: str
    provider: str
    model: str
    api_key_env: Optional[str]
    base_url: str
    price: Optional[Price]

    def public_dict(self) -> Dict[str, Any]:
        """Serializable view. Contains env var *names* only, never values."""
        return {
            "id": self.id,
            "provider": self.provider,
            "model": self.model,
            "api_key_env": self.api_key_env,
            "base_url": self.base_url,
            "price_per_million": None
            if self.price is None
            else {
                "input": self.price.input,
                "output": self.price.output,
                "cached_input": self.price.cached_input,
                "source": self.price.source,
                "checked": self.price.checked,
            },
        }


@dataclass(frozen=True)
class Settings:
    max_output_tokens: int
    timeout_s: float = 60.0
    temperature: Optional[float] = None
    system: Optional[str] = None


@dataclass
class Usage:
    uncached_input: Optional[int] = None
    cached_input: int = 0
    output: Optional[int] = None

    @property
    def known(self) -> bool:
        return self.uncached_input is not None and self.output is not None


@dataclass
class CallResult:
    text: str
    usage: Usage
    latency_ms: float
    retries: int = 0
    raw_finish: Optional[str] = None
    notes: List[str] = field(default_factory=list)


# --------------------------------------------------------------------------
# Validation
# --------------------------------------------------------------------------
def _is_loopback(host: str) -> bool:
    if host in ("localhost",):
        return True
    try:
        return ipaddress.ip_address(host.strip("[]")).is_loopback
    except ValueError:
        return False


def validate_base_url(url: str) -> str:
    if not isinstance(url, str) or len(url) > 300:
        raise ConfigError("base_url must be a string under 300 characters.")
    parts = urllib.parse.urlsplit(url)
    if parts.username or parts.password:
        raise ConfigError("base_url must not contain credentials.")
    host = parts.hostname or ""
    if not host:
        raise ConfigError(f"base_url has no host: {url!r}")
    if parts.scheme == "https":
        pass
    elif parts.scheme == "http" and _is_loopback(host):
        pass
    else:
        raise ConfigError("base_url must use https (http is allowed only for localhost/loopback).")
    if parts.query or parts.fragment:
        raise ConfigError("base_url must not include a query string or fragment.")
    return url.rstrip("/")


def number_in_range(value: Any, name: str, lo: float, hi: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ConfigError(f"{name} must be a finite number.")
    if not lo <= value <= hi:
        raise ConfigError(f"{name} must be between {lo} and {hi}.")
    return float(value)


def validate_price(raw: Any, where: str) -> Optional[Price]:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ConfigError(f"{where}: price_per_million must be an object or null.")
    cached = raw.get("cached_input")
    price = Price(
        input=number_in_range(raw.get("input"), f"{where}: price input", 0, 10_000),
        output=number_in_range(raw.get("output"), f"{where}: price output", 0, 10_000),
        cached_input=None if cached is None else number_in_range(cached, f"{where}: price cached_input", 0, 10_000),
        source=str(raw.get("source", ""))[:500],
        checked=str(raw.get("checked", ""))[:40],
    )
    if not price.source or not price.checked:
        raise ConfigError(
            f"{where}: price needs 'source' (official URL) and 'checked' (date). "
            "Use null if the price is not verified."
        )
    return price


def validate_candidate(raw: Any, index: int) -> Candidate:
    where = f"candidates[{index}]"
    if not isinstance(raw, dict):
        raise ConfigError(f"{where} must be an object.")
    forbidden = {"api_key", "key", "token", "secret", "authorization"} & {k.lower() for k in raw}
    if forbidden:
        raise ConfigError(
            f"{where}: remove {sorted(forbidden)}. Put the key in an environment variable "
            "and reference it with 'api_key_env'."
        )
    cid = raw.get("id")
    if not isinstance(cid, str) or not _ID_RE.match(cid):
        raise ConfigError(f"{where}: 'id' must be 1-64 chars of letters, digits, '.', '_' or '-'.")
    provider = raw.get("provider")
    if provider not in PROVIDERS:
        raise ConfigError(f"{where}: 'provider' must be one of {', '.join(PROVIDERS)}.")
    model = raw.get("model")
    if not isinstance(model, str) or not _MODEL_RE.match(model):
        raise ConfigError(f"{where}: 'model' must be the exact provider model ID (no spaces).")
    env = raw.get("api_key_env")
    if env is not None and (not isinstance(env, str) or not _ENV_RE.match(env)):
        raise ConfigError(f"{where}: 'api_key_env' must be an UPPER_SNAKE environment variable name.")
    if env is None and provider != "openai_compatible":
        raise ConfigError(f"{where}: 'api_key_env' is required for provider {provider}.")
    base = raw.get("base_url")
    if base is None:
        if provider == "openai_compatible":
            raise ConfigError(f"{where}: 'base_url' is required for openai_compatible.")
        base = DEFAULT_BASE_URLS[provider]
    base = validate_base_url(base)
    return Candidate(cid, provider, model, env, base, validate_price(raw.get("price_per_million"), where))


def validate_settings(raw: Any) -> Settings:
    if not isinstance(raw, dict):
        raise ConfigError("'settings' must be an object.")
    max_out = raw.get("max_output_tokens")
    if isinstance(max_out, bool) or not isinstance(max_out, int) or not 1 <= max_out <= MAX_OUTPUT_TOKENS:
        raise ConfigError(f"settings.max_output_tokens must be an integer 1-{MAX_OUTPUT_TOKENS}.")
    temp = raw.get("temperature")
    system = raw.get("system")
    if system is not None and (not isinstance(system, str) or len(system) > 50_000):
        raise ConfigError("settings.system must be a string under 50,000 characters.")
    return Settings(
        max_output_tokens=max_out,
        timeout_s=number_in_range(raw.get("timeout_s", 60), "settings.timeout_s", 1, 600),
        temperature=None if temp is None else number_in_range(temp, "settings.temperature", 0, 2),
        system=system,
    )


def validate_checks(raw: Any, where: str, allow_empty: bool = False) -> List[Dict[str, Any]]:
    if not isinstance(raw, list) or (not raw and not allow_empty) or len(raw) > 50:
        raise ConfigError(f"{where}: 'checks' must be a list of 1-50 checks.")
    out: List[Dict[str, Any]] = []
    for i, check in enumerate(raw):
        loc = f"{where}.checks[{i}]"
        if not isinstance(check, dict) or check.get("type") not in CHECK_TYPES:
            raise ConfigError(f"{loc}: 'type' must be one of {', '.join(CHECK_TYPES)}.")
        kind = check["type"]
        if kind in ("contains", "not_contains", "exact"):
            value = check.get("value")
            if not isinstance(value, str) or not value or len(value) > 10_000:
                raise ConfigError(f"{loc}: 'value' must be a non-empty string.")
            out.append({"type": kind, "value": value, "ignore_case": bool(check.get("ignore_case", False))})
        elif kind == "regex":
            pattern = check.get("pattern")
            if not isinstance(pattern, str) or not pattern or len(pattern) > MAX_PATTERN_CHARS:
                raise ConfigError(f"{loc}: 'pattern' must be a string up to {MAX_PATTERN_CHARS} chars.")
            try:
                re.compile(pattern)
            except re.error as exc:
                raise ConfigError(f"{loc}: invalid regex ({exc}).") from None
            out.append({"type": kind, "pattern": pattern})
        elif kind == "json_keys":
            keys = check.get("keys")
            if not isinstance(keys, list) or not keys or not all(isinstance(k, str) and k for k in keys):
                raise ConfigError(f"{loc}: 'keys' must be a non-empty list of strings.")
            out.append({"type": kind, "keys": keys})
        else:  # max_chars
            limit = check.get("value")
            if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
                raise ConfigError(f"{loc}: 'value' must be a positive integer.")
            out.append({"type": kind, "value": limit})
    return out


# --------------------------------------------------------------------------
# Deterministic checks
# --------------------------------------------------------------------------
def _extract_json(text: str) -> Any:
    """Parse JSON from a reply, tolerating a single fenced code block."""
    stripped = text.strip()
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", stripped, re.DOTALL)
    if fence:
        stripped = fence.group(1)
    return json.loads(stripped)


def run_checks(text: str, checks: List[Dict[str, Any]]) -> List[str]:
    """Return human-readable descriptions of failed checks (empty = pass)."""
    failures: List[str] = []
    for check in checks:
        kind = check["type"]
        if kind in ("contains", "not_contains", "exact"):
            subject, value = text, check["value"]
            if check.get("ignore_case"):
                subject, value = subject.lower(), value.lower()
            if kind == "contains" and value not in subject:
                failures.append(f"missing {check['value']!r}")
            elif kind == "not_contains" and value in subject:
                failures.append(f"contains forbidden {check['value']!r}")
            elif kind == "exact" and subject.strip() != value.strip():
                failures.append("not an exact match")
        elif kind == "regex":
            if not re.search(check["pattern"], text[:MAX_REGEX_SUBJECT_CHARS]):
                failures.append(f"no match for /{check['pattern']}/")
        elif kind == "json_keys":
            try:
                parsed = _extract_json(text)
            except (json.JSONDecodeError, ValueError):
                failures.append("not valid JSON")
                continue
            if not isinstance(parsed, dict):
                failures.append("JSON is not an object")
                continue
            missing = [k for k in check["keys"] if k not in parsed]
            if missing:
                failures.append(f"JSON missing keys {missing}")
        elif kind == "max_chars" and len(text) > check["value"]:
            failures.append(f"longer than {check['value']} chars")
    return failures


# --------------------------------------------------------------------------
# Sensitive-data guard (personal data and secrets)
# --------------------------------------------------------------------------
# Detects common identifiers so personal data is not sent to model providers
# by accident. Reports categories and counts only, never the matched values,
# so the guard itself cannot leak what it finds. Pattern matching is a
# safeguard, not a guarantee: names, addresses and free-text personal details
# are not detected, and some matches may be false positives.
PERSONAL_CATEGORIES = ("aadhaar", "pan", "payment_card", "email", "upi_id", "indian_mobile")
SECRET_CATEGORY = "secret"
MAX_SCAN_CHARS = 1_000_000

_SECRET_RES = [
    re.compile(r"\bsk-(?:ant-|proj-)?[A-Za-z0-9_-]{20,}"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b"),
    re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}"),
    re.compile(r"-----BEGIN (?:[A-Z]+ )?PRIVATE KEY-----"),
]
_CARD_RE = re.compile(r"(?<![\d.])\d(?:[ -]?\d){12,18}(?![\d.])")
_AADHAAR_RE = re.compile(r"(?<![\d.])[2-9]\d{3}[ -]?\d{4}[ -]?\d{4}(?![\d.])")
_PAN_RE = re.compile(r"\b[A-Z]{3}[ABCFGHJLPT][A-Z]\d{4}[A-Z]\b")
_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}\b")
_UPI_RE = re.compile(r"(?<![\w.@-])[A-Za-z0-9._-]{2,256}@[A-Za-z]{2,64}(?![\w.@-])")
_MOBILE_RE = re.compile(r"(?<![\d+])(?:\+91[ -]?|91[ -]?|0)?[6-9]\d{4}[ -]?\d{5}(?!\d)")

# Verhoeff checksum tables (used by Aadhaar).
_V_D = [[0, 1, 2, 3, 4, 5, 6, 7, 8, 9], [1, 2, 3, 4, 0, 6, 7, 8, 9, 5],
        [2, 3, 4, 0, 1, 7, 8, 9, 5, 6], [3, 4, 0, 1, 2, 8, 9, 5, 6, 7],
        [4, 0, 1, 2, 3, 9, 5, 6, 7, 8], [5, 9, 8, 7, 6, 0, 4, 3, 2, 1],
        [6, 5, 9, 8, 7, 1, 0, 4, 3, 2], [7, 6, 5, 9, 8, 2, 1, 0, 4, 3],
        [8, 7, 6, 5, 9, 3, 2, 1, 0, 4], [9, 8, 7, 6, 5, 4, 3, 2, 1, 0]]
_V_P = [[0, 1, 2, 3, 4, 5, 6, 7, 8, 9], [1, 5, 7, 6, 2, 8, 3, 0, 9, 4],
        [5, 8, 0, 3, 7, 9, 6, 1, 4, 2], [8, 9, 1, 6, 0, 4, 3, 5, 2, 7],
        [9, 4, 5, 3, 1, 2, 6, 8, 7, 0], [4, 2, 8, 6, 5, 7, 3, 9, 0, 1],
        [2, 7, 9, 3, 8, 0, 6, 4, 1, 5], [7, 0, 4, 6, 9, 1, 3, 2, 5, 8]]


def verhoeff_valid(digits: str) -> bool:
    check = 0
    for i, ch in enumerate(reversed(digits)):
        check = _V_D[check][_V_P[i % 8][int(ch)]]
    return check == 0


def luhn_valid(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        n = int(ch)
        if i % 2:
            n = n * 2 - 9 if n > 4 else n * 2
        total += n
    return total % 10 == 0


def detect_sensitive(text: str) -> Dict[str, int]:
    """Return {category: count} for personal data and secrets found in text.

    Matched spans are blanked before later detectors run, so one value is
    counted once (an Aadhaar number is not also reported as a phone number).
    """
    if not isinstance(text, str) or not text:
        return {}
    work = text[:MAX_SCAN_CHARS]
    found: Dict[str, int] = {}

    def take(pattern: "re.Pattern[str]", category: str, check=None) -> None:
        nonlocal work
        spans = []
        for match in pattern.finditer(work):
            if check is None or check(re.sub(r"[ -]", "", match.group(0))):
                spans.append(match.span())
        if spans:
            found[category] = found.get(category, 0) + len(spans)
            chars = list(work)
            for start, end in spans:
                chars[start:end] = " " * (end - start)
            work = "".join(chars)

    for pattern in _SECRET_RES:
        take(pattern, SECRET_CATEGORY)
    take(_CARD_RE, "payment_card", lambda d: 13 <= len(d) <= 19 and len(set(d)) > 1 and luhn_valid(d))
    take(_AADHAAR_RE, "aadhaar", lambda d: len(d) == 12 and verhoeff_valid(d))
    take(_PAN_RE, "pan")
    take(_EMAIL_RE, "email")
    take(_UPI_RE, "upi_id")
    take(_MOBILE_RE, "indian_mobile")
    return found


def split_findings(found: Dict[str, int]) -> tuple:
    """(personal_data_counts, secret_count)."""
    personal = {k: v for k, v in found.items() if k in PERSONAL_CATEGORIES}
    return personal, found.get(SECRET_CATEGORY, 0)


def describe_findings(found: Dict[str, int]) -> str:
    return ", ".join(f"{k} ×{v}" for k, v in sorted(found.items())) or "none"


# --------------------------------------------------------------------------
# Cost
# --------------------------------------------------------------------------
def compute_cost(usage: Usage, price: Optional[Price]) -> Optional[float]:
    """USD cost, or None when price or token usage is unknown (never 0 by default)."""
    if price is None or not usage.known:
        return None
    cached_rate = price.cached_input if price.cached_input is not None else price.input
    total = (
        (usage.uncached_input or 0) * price.input
        + usage.cached_input * cached_rate
        + (usage.output or 0) * price.output
    )
    return total / 1_000_000


def estimate_monthly_cost(requests_per_month: float, input_tokens: float, output_tokens: float,
                          input_price: float, output_price: float, cached_fraction: float = 0.0,
                          cached_input_price: Optional[float] = None,
                          pass_rate: Optional[float] = None) -> Dict[str, Any]:
    """Planning estimate from per-request averages and USD-per-million prices.

    cached_fraction is the share of input tokens billed at the cached rate. When
    pass_rate is given, cost per accepted result assumes failures are retried
    until one passes (expected attempts = 1 / pass_rate).
    """
    requests_per_month = number_in_range(requests_per_month, "requests_per_month", 0, 1e12)
    input_tokens = number_in_range(input_tokens, "input_tokens", 0, 1e8)
    output_tokens = number_in_range(output_tokens, "output_tokens", 0, 1e8)
    input_price = number_in_range(input_price, "input_price", 0, 10_000)
    output_price = number_in_range(output_price, "output_price", 0, 10_000)
    cached_fraction = number_in_range(cached_fraction, "cached_fraction", 0, 1)
    if cached_fraction and cached_input_price is None:
        raise ConfigError("cached_input_price is required when cached_fraction is above 0.")
    cached_rate = input_price if cached_input_price is None else number_in_range(
        cached_input_price, "cached_input_price", 0, 10_000)
    per_request = (input_tokens * (1 - cached_fraction) * input_price
                   + input_tokens * cached_fraction * cached_rate
                   + output_tokens * output_price) / 1_000_000
    result: Dict[str, Any] = {
        "cost_per_request_usd": per_request,
        "monthly_cost_usd": per_request * requests_per_month,
        "assumptions": [
            "Token charges only: tools, storage, batch discounts, tiered pricing and taxes are excluded.",
            "Prices are whatever was supplied; confirm them on the provider's official pricing page.",
        ],
    }
    if pass_rate is not None:
        pass_rate = number_in_range(pass_rate, "pass_rate", 0.000001, 1)
        result["cost_per_accepted_result_usd"] = per_request / pass_rate
        result["monthly_cost_with_retries_usd"] = per_request * requests_per_month / pass_rate
        result["assumptions"].append("Failed requests are retried until one passes (1 / pass_rate attempts).")
    for key, value in result.items():  # drop floating-point noise such as 2.6999999999999997
        if isinstance(value, float):
            result[key] = round(value, 10)
    return result


# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------
class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[override]
        raise ModelCallError(f"Refused HTTP {code} redirect (credentials are never forwarded).")


_OPENER = urllib.request.build_opener(_NoRedirect())


def _read_key(candidate: Candidate) -> Optional[str]:
    if candidate.api_key_env is None:
        return None
    value = os.environ.get(candidate.api_key_env, "").strip()
    if not value:
        raise ModelCallError(f"Environment variable {candidate.api_key_env} is not set.")
    return value


def _scrub(text: str, secret: Optional[str]) -> str:
    text = text[:500]
    return text.replace(secret, "[redacted]") if secret else text


def _post_json(url: str, headers: Dict[str, str], body: Dict[str, Any], timeout: float,
               secret: Optional[str]) -> tuple:
    data = json.dumps(body).encode("utf-8")
    retries = 0
    while True:
        request = urllib.request.Request(url, data=data, method="POST")
        request.add_header("Content-Type", "application/json")
        for name, value in headers.items():
            request.add_unredirected_header(name, value)
        try:
            with _OPENER.open(request, timeout=timeout) as response:
                payload = response.read(MAX_RESPONSE_BYTES + 1)
            if len(payload) > MAX_RESPONSE_BYTES:
                raise ModelCallError("Response exceeded the 10 MiB limit.")
            return json.loads(payload.decode("utf-8")), retries
        except urllib.error.HTTPError as exc:
            status = exc.code
            detail = _scrub(exc.read(2000).decode("utf-8", "replace"), secret)
            if (status == 429 or status >= 500) and retries < MAX_RETRIES:
                wait = 2.0 ** retries
                retry_after = exc.headers.get("Retry-After") if exc.headers else None
                if retry_after and retry_after.strip().isdigit():
                    wait = float(retry_after.strip())
                time.sleep(min(wait, MAX_RETRY_WAIT_S))
                retries += 1
                continue
            raise ModelCallError(f"HTTP {status}: {detail}") from None
        except urllib.error.URLError as exc:
            raise ModelCallError(f"Network error: {_scrub(str(exc.reason), secret)}") from None
        except json.JSONDecodeError:
            raise ModelCallError("Provider returned non-JSON content.") from None


# --------------------------------------------------------------------------
# Provider adapters
# --------------------------------------------------------------------------
def _int_or_none(value: Any) -> Optional[int]:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def call_model(candidate: Candidate, prompt: str, settings: Settings) -> CallResult:
    """Send one prompt and return text, normalized usage, and latency."""
    key = _read_key(candidate)
    started = time.perf_counter()
    if candidate.provider == "anthropic":
        body: Dict[str, Any] = {
            "model": candidate.model,
            "max_tokens": settings.max_output_tokens,
            "messages": [{"role": "user", "content": prompt}],
        }
        if settings.system:
            body["system"] = settings.system
        if settings.temperature is not None:
            body["temperature"] = settings.temperature
        headers = {"x-api-key": key or "", "anthropic-version": ANTHROPIC_VERSION}
        data, retries = _post_json(f"{candidate.base_url}/v1/messages", headers, body, settings.timeout_s, key)
        blocks = data.get("content") if isinstance(data, dict) else None
        text = "".join(b.get("text", "") for b in blocks or [] if isinstance(b, dict) and b.get("type") == "text")
        u = data.get("usage") or {}
        usage = Usage(_int_or_none(u.get("input_tokens")), _int_or_none(u.get("cache_read_input_tokens")) or 0,
                      _int_or_none(u.get("output_tokens")))
        finish = data.get("stop_reason")
    elif candidate.provider == "gemini":
        body = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"maxOutputTokens": settings.max_output_tokens},
        }
        if settings.system:
            body["systemInstruction"] = {"parts": [{"text": settings.system}]}
        if settings.temperature is not None:
            body["generationConfig"]["temperature"] = settings.temperature
        model_path = urllib.parse.quote(candidate.model, safe="")
        url = f"{candidate.base_url}/v1beta/models/{model_path}:generateContent"
        data, retries = _post_json(url, {"x-goog-api-key": key or ""}, body, settings.timeout_s, key)
        cands = data.get("candidates") or []
        first = cands[0] if cands and isinstance(cands[0], dict) else {}
        parts = (first.get("content") or {}).get("parts") or []
        text = "".join(p.get("text", "") for p in parts if isinstance(p, dict) and not p.get("thought"))
        u = data.get("usageMetadata") or {}
        prompt_tokens = _int_or_none(u.get("promptTokenCount"))
        cached = _int_or_none(u.get("cachedContentTokenCount")) or 0
        visible = _int_or_none(u.get("candidatesTokenCount")) or 0
        thoughts = _int_or_none(u.get("thoughtsTokenCount")) or 0
        usage = Usage(None if prompt_tokens is None else max(prompt_tokens - cached, 0), cached,
                      None if prompt_tokens is None else visible + thoughts)
        finish = first.get("finishReason")
    else:  # openai, openai_compatible (Chat Completions)
        body = {"model": candidate.model, "messages": []}
        if settings.system:
            body["messages"].append({"role": "system", "content": settings.system})
        body["messages"].append({"role": "user", "content": prompt})
        token_field = "max_completion_tokens" if candidate.provider == "openai" else "max_tokens"
        body[token_field] = settings.max_output_tokens
        if settings.temperature is not None:
            body["temperature"] = settings.temperature
        headers = {"Authorization": f"Bearer {key}"} if key else {}
        data, retries = _post_json(f"{candidate.base_url}/v1/chat/completions", headers, body,
                                   settings.timeout_s, key)
        choices = data.get("choices") or []
        first = choices[0] if choices and isinstance(choices[0], dict) else {}
        text = (first.get("message") or {}).get("content") or ""
        u = data.get("usage") or {}
        prompt_tokens = _int_or_none(u.get("prompt_tokens"))
        cached = _int_or_none((u.get("prompt_tokens_details") or {}).get("cached_tokens")) or 0
        usage = Usage(None if prompt_tokens is None else max(prompt_tokens - cached, 0), cached,
                      _int_or_none(u.get("completion_tokens")))
        finish = first.get("finish_reason")
    latency = (time.perf_counter() - started) * 1000
    result = CallResult(text=text if isinstance(text, str) else "", usage=usage, latency_ms=latency,
                        retries=retries, raw_finish=finish if isinstance(finish, str) else None)
    if not usage.known:
        result.notes.append("provider did not report token usage; cost unknown")
    if usage.cached_input and candidate.price and candidate.price.cached_input is None:
        result.notes.append("cached tokens billed at full input price (no cached price supplied)")
    return result
