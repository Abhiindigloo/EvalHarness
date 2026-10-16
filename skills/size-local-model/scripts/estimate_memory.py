#!/usr/bin/env python3
"""Estimate memory for running a model locally: weights + optional KV cache.

Usage:
  python3 estimate_memory.py --params-b 8.03 --bits 16 \
      [--layers 32 --kv-heads 8 --head-dim 128 --context 8192 --concurrency 1 --kv-bits 16] \
      [--overhead-pct 10] [--available-gib 24] [--json]

Formulas (binary GiB = 2^30 bytes):
  weights  = params × bits_per_weight ÷ 8
  kv_cache = 2 (K and V) × layers × kv_heads × head_dim × context × concurrency × kv_bits ÷ 8

The KV formula assumes standard full attention (MHA or GQA). It does NOT apply to
multi-head latent attention (MLA), sliding-window, hybrid, or linear attention;
use the runtime's documentation for those. Results are estimates, not a
guarantee that a model fits: runtimes add buffers, activations, and fragmentation.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import asdict, dataclass
from typing import List, Optional

GIB = 2 ** 30


@dataclass(frozen=True)
class Estimate:
    weights_gib: float
    kv_cache_gib: Optional[float]
    kv_per_token_kib: Optional[float]
    overhead_gib: float
    total_gib: float
    headroom_gib: Optional[float]
    caveats: List[str]


def _check(name: str, value: float, lo: float, hi: float) -> float:
    if not math.isfinite(value) or not lo <= value <= hi:
        raise ValueError(f"{name} must be between {lo:g} and {hi:g}.")
    return value


def estimate(params_b: float, bits: float, overhead_pct: float = 0.0,
             layers: Optional[int] = None, kv_heads: Optional[int] = None,
             head_dim: Optional[int] = None, context: Optional[int] = None,
             concurrency: int = 1, kv_bits: float = 16.0,
             available_gib: Optional[float] = None) -> Estimate:
    """Pure calculation; raises ValueError on invalid inputs."""
    _check("params-b (billions of total stored parameters)", params_b, 0.001, 10_000)
    _check("bits (effective bits per weight)", bits, 1, 32)
    _check("overhead-pct", overhead_pct, 0, 200)
    _check("concurrency", concurrency, 1, 4_096)
    _check("kv-bits", kv_bits, 1, 32)
    if available_gib is not None:
        _check("available-gib", available_gib, 0, 100_000)

    weights = params_b * 1e9 * bits / 8 / GIB
    kv_fields = (layers, kv_heads, head_dim, context)
    caveats = ["Estimate only: runtime buffers, activations, and fragmentation are not modeled exactly."]
    kv_gib: Optional[float] = None
    per_token_kib: Optional[float] = None
    if any(f is not None for f in kv_fields):
        if any(f is None for f in kv_fields):
            raise ValueError("KV cache needs all of --layers, --kv-heads, --head-dim and --context.")
        _check("layers", layers, 1, 1_000)  # type: ignore[arg-type]
        _check("kv-heads", kv_heads, 1, 1_024)  # type: ignore[arg-type]
        _check("head-dim", head_dim, 1, 4_096)  # type: ignore[arg-type]
        _check("context", context, 1, 10_000_000)  # type: ignore[arg-type]
        per_token_bytes = 2 * layers * kv_heads * head_dim * kv_bits / 8  # type: ignore[operator]
        per_token_kib = per_token_bytes / 1024
        kv_gib = per_token_bytes * context * concurrency / GIB  # type: ignore[operator]
        caveats.append("KV formula assumes standard full attention (MHA/GQA); MLA, sliding-window, "
                       "hybrid and linear attention need model-specific formulas.")
    else:
        caveats.append("KV cache not included: supply --layers --kv-heads --head-dim --context "
                       "from the model card to estimate it.")
    base = weights + (kv_gib or 0.0)
    overhead = base * overhead_pct / 100
    total = base + overhead
    if overhead_pct == 0:
        caveats.append("No overhead allowance applied (--overhead-pct 0).")
    return Estimate(
        weights_gib=weights,
        kv_cache_gib=kv_gib,
        kv_per_token_kib=per_token_kib,
        overhead_gib=overhead,
        total_gib=total,
        headroom_gib=None if available_gib is None else available_gib - total,
        caveats=caveats,
    )


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--params-b", type=float, required=True, help="total stored parameters, in billions")
    p.add_argument("--bits", type=float, required=True, help="effective bits per weight, e.g. 16, 8, 4.5")
    p.add_argument("--overhead-pct", type=float, default=0.0)
    p.add_argument("--layers", type=int)
    p.add_argument("--kv-heads", type=int, help="number of key/value heads (GQA groups)")
    p.add_argument("--head-dim", type=int)
    p.add_argument("--context", type=int, help="tokens of context per sequence")
    p.add_argument("--concurrency", type=int, default=1, help="simultaneous sequences")
    p.add_argument("--kv-bits", type=float, default=16.0, help="KV cache precision in bits")
    p.add_argument("--available-gib", type=float)
    p.add_argument("--json", action="store_true")
    a = p.parse_args(argv)
    try:
        est = estimate(a.params_b, a.bits, a.overhead_pct, a.layers, a.kv_heads, a.head_dim,
                       a.context, a.concurrency, a.kv_bits, a.available_gib)
    except ValueError as exc:
        print(f"Input error: {exc}", file=sys.stderr)
        return 2
    if a.json:
        print(json.dumps(asdict(est), indent=2))
        return 0
    print(f"Weights:   {est.weights_gib:,.2f} GiB")
    if est.kv_cache_gib is not None:
        print(f"KV cache:  {est.kv_cache_gib:,.2f} GiB ({est.kv_per_token_kib:,.1f} KiB per token)")
    print(f"Overhead:  {est.overhead_gib:,.2f} GiB")
    print(f"Total:     {est.total_gib:,.2f} GiB")
    if est.headroom_gib is not None:
        verdict = "remaining" if est.headroom_gib >= 0 else "over budget"
        print(f"Headroom:  {abs(est.headroom_gib):,.2f} GiB {verdict}")
    for note in est.caveats:
        print(f"Note: {note}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
