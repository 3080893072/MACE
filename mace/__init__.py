"""MACE: Masking-Aware Contract Engine (research prototype).

Modules
-------
terms      typed, non-executing expression language for contracts
program    paired program representation, subset gate, execution harness
domain     finite input domains
contracts  structured LLM contract schema
verify     bounded verification of observer soundness / target invariance
sandbox    isolated child-process driver
qwen       local model client
prompts    prompt construction
loop       counterexample-guided experiment driver
fixture    experiment fixture loading
cli        command line entry point
"""

__version__ = "0.2.0"
