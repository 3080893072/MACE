"""Fair baselines for MACE Benchmark v3 (development/pilot).

This package is intentionally separate from ``mace`` and from
``benchmark_real_v3.scoring``.  Nothing here imports the hidden reference
data; every module reads only the PUBLIC task package, the public probes and
the project source trees.
"""
from __future__ import annotations

__all__ = ["config", "public_io", "execution", "ast_discovery", "inputs",
           "claims", "direct_qwen", "verifier"]
