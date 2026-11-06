#!/usr/bin/env python3
"""MACE pilot: Qwen semantic-guard proposal -> bounded verification -> feedback.

IMPORTANT SCIENTIFIC LIMITS
- This is a pilot, not a complete MACE implementation or formal proof.
- The local AST example is a controlled fixture, not an untrusted-code sandbox.
- The baseline prompt asks for a guard; it does not yet verify LLM-derived
  intermediate observer contracts or perform proof-grounded source attribution.
- --mock only tests the plumbing. Never report its results as model performance.

Examples:
  python mace_qwen_pilot.py --smoke
  python mace_qwen_pilot.py --model qwen2.5-coder:7b --mode target
  python mace_qwen_pilot.py --model qwen3-coder:30b --mode all
  python mace_qwen_pilot.py --provider dashscope --model qwen-plus --mode target
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import time
import urllib.error
import urllib.request

from mace_semantic_core_poc import PROGRAM_SOURCE, check_guard, finite_domain, make_versions

SYSTEM = (
    "You are a precise program-semantics analyst. A named target assignment A will be "
    "deleted in one version of a Python program. Infer conditions under which the "
    "original and A-deleted programs have the SAME observable output. Derive relations "
    "from actual source code, including loops and branch conditions. Do not guess "
    "candidate operations to delete. Do not claim a statement has been formally "
    "proved merely because it is plausible. Respond as a single valid JSON object."
)

SCHEMA = {
    "target_effect": "plain-language description of the semantic effect of deleting A",
    "observer_relations": [
        {"source": "exact source snippet supporting the relation",
         "condition": "under what input/branch condition this applies",
         "relation": "a relation on input/output state, not just a paraphrase"}
    ],
    "mask_guard": "a single Boolean expression in the allowed guard language",
    "uncertainty": "what remains unverified or unsupported",
}

# A target-language whitelist, not a whitelist of semantic equivalence relations.
GUARD_LANGUAGE = (
    "Legal variables: xs (a nonempty list of ints), pre, use_left, use_right. "
    "Legal syntax: and, or, not, parentheses, ==, True, False, "
    "xs[0], xs[-1], min(xs), max(xs). "
    "Do not use sorted(), all(), any(), len(), comprehensions, arithmetic, "
    "helper function names, output function calls, or other Python syntax. "
    "A mask guard must evaluate to True exactly when deleting A preserves "
    "the program's returned value, for the indicated input domain."
)


def obfuscate_function_names(source: str) -> str:
    # Keep program() and the TARGET_A marker; remove descriptive helper names.
    result = source
    for name, replacement in (
        ("stable_order", "fn_0"),
        ("fold_one", "fn_1"),
        ("fold_two", "fn_2"),
    ):
        result = re.sub(r"\b" + name + r"\b", replacement, result)
    return result


def raw_chat_request(provider: str, model: str, messages: list[dict], endpoint: str,
                     temperature: float, seed: int, num_ctx: int, timeout: int):
    if provider == "ollama":
        url = endpoint.rstrip("/") + "/api/chat"
        payload = {
            "model": model, "messages": messages, "stream": False,
            "format": "json", "options": {
                "temperature": temperature, "seed": seed, "num_ctx": num_ctx
            }
        }
        headers = {"Content-Type": "application/json"}
    else:
        key = os.environ.get("DASHSCOPE_API_KEY", "")
        if not key:
            raise RuntimeError(
                "DASHSCOPE_API_KEY is not set. Set it on your own machine, "
                "never paste it into chat or an experiment log."
            )
        url = endpoint.rstrip("/") + "/chat/completions"
        payload = {"model": model, "messages": messages, "temperature": temperature,
                   "stream": False}
        headers = {"Content-Type": "application/json", "Authorization": "Bearer " + key}

    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers=headers, method="POST")
    start = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")[:600]
        raise RuntimeError(f"{provider} HTTP {error.code}: {detail}") from error
    except urllib.error.URLError as error:
        raise RuntimeError(f"Cannot reach {provider} at {url}: {error.reason}") from error
    elapsed = round(time.perf_counter() - start, 3)
    obj = json.loads(body)
    if provider == "ollama":
        content = obj.get("message", {}).get("content", "")
        stats = {
            "prompt_tokens": obj.get("prompt_eval_count"),
            "completion_tokens": obj.get("eval_count"),
            "duration_seconds": elapsed,
            "model": obj.get("model")
        }
    else:
        content = obj["choices"][0]["message"]["content"]
        if isinstance(content, list):
            content = "".join(item.get("text", "") for item in content if isinstance(item, dict))
        stats = {"usage": obj.get("usage", {}), "duration_seconds": elapsed,
                 "model": obj.get("model")}
    return content, stats


def parse_model_json(content: str) -> dict:
    if not content or not isinstance(content, str):
        raise ValueError("Model response has no text content")
    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    obj = json.loads(text)
    if not isinstance(obj, dict):
        raise ValueError("Expected a JSON object")
    guard = obj.get("mask_guard")
    if not isinstance(guard, str) or not guard.strip():
        raise ValueError("Response needs nonempty 'mask_guard' string")
    return obj


def provide_code_input(source: str, target_line: int) -> str:
    return (
        "Input domain: xs is a nonempty list of integers; pre, use_left, "
        "use_right are Booleans. The program is deterministic and returns "
        "a pair of ints. The goal is to explain only the returned result.\n"
        f"The only marked target A is at line {target_line}.\n"
        "Source (line-numbered; line numbers are not part of code):\n"
        + "\n".join(f"{i:03}: {line}" for i, line in enumerate(source.splitlines(), 1))
    )


def make_prompt(mode: str, source: str, line: int, generic_summary: str = "") -> str:
    code = provide_code_input(source, line)
    if mode == "target":
        method = (
            "Target-relative relational reasoning: derive A's local state change; "
            "analyze each returned component in terms of the information it observes; "
            "derive relevant loop invariants from function bodies; compose the "
            "observer relations and their branch guards without enumerating "
            "source-operation subsets. Include source snippets for claims."
        )
    elif mode == "generic":
        method = (
            "Use these generic function summaries to reason about the A-deletion "
            "equivalence condition. They were generated without the target-A task:\n"
            f"{generic_summary}"
        )
    elif mode == "direct":
        method = (
            "Direct baseline: read the whole source and directly infer when "
            "deleting the marked A changes the final returned result."
        )
    else:
        raise ValueError(mode)
    return (
        code + "\n\n" + method + "\n\n" + GUARD_LANGUAGE + "\n\n"
        "Output JSON with precisely these top-level fields (values are examples "
        "of types, NOT a solution):\n" + json.dumps(SCHEMA, ensure_ascii=False)
    )


def generic_summary_prompt(source: str) -> str:
    return (
        "Summarize all user-defined functions in this Python source. "
        "Do not study a target deletion or predict masking. "
        "Summarize loops, functional invariants, input/output relations and "
        "which information the final return values depend on. "
        "Write compact JSON with the key 'functions'.\n\n" + source
    )


def format_case(original, without_a, state: dict) -> dict:
    args = (state["xs"], state["pre"], state["use_left"], state["use_right"])
    with_a, without = original(*args), without_a(*args)
    return {"input": state, "with_A": with_a, "without_A": without,
            "outputs_equal": with_a == without,
            "A_has_local_effect": sorted(state["xs"]) != state["xs"] and not state["pre"]}


def preferred_counterexample(original, without_a, guard: str, want: str):
    # Choose a counterexample with A's local change if possible, so feedback
    # reveals a missing observer relation rather than a trivial fixed-point.
    from mace_semantic_core_poc import eval_guard
    fallback = None
    for state in finite_domain():
        args = (state["xs"], state["pre"], state["use_left"], state["use_right"])
        real = original(*args) == without_a(*args)
        predicted = eval_guard(guard, state)
        wrong = predicted and not real if want == "unsound" else real and not predicted
        if wrong:
            case = format_case(original, without_a, state)
            if case["A_has_local_effect"]:
                return case
            if fallback is None:
                fallback = case
    return fallback


def guard_report(original, without_a, candidate):
    try:
        report = check_guard(original, without_a, candidate, finite_domain())
        if report["soundness_counterexamples"]:
            report["preferred_unsound"] = preferred_counterexample(
                original, without_a, candidate, "unsound"
            )
        if report["completeness_counterexamples"]:
            report["preferred_incomplete"] = preferred_counterexample(
                original, without_a, candidate, "incomplete"
            )
        return report
    except (SyntaxError, ValueError, TypeError, IndexError) as exc:
        return {"invalid_guard": str(exc), "accepted": False}


def feedback_text(guard: str | None, validation: dict, invalid_json: str = "") -> str:
    if invalid_json:
        return (
            f"Your previous response could not be parsed: {invalid_json}. "
            "Return valid JSON matching the specified fields. "
            + GUARD_LANGUAGE
        )
    if "invalid_guard" in validation:
        return (
            f"Your mask_guard was invalid: {validation['invalid_guard']}. "
            "Correct the *expression syntax* while preserving the intended "
            "source-grounded reasoning. " + GUARD_LANGUAGE
        )
    msg = [f"Candidate guard: {guard}."]
    msg.append("The bounded verifier found the following issues:")
    if validation.get("preferred_unsound"):
        msg.append(
            "UNSOUND: the guard predicts output equality, but a paired run differs: "
            + json.dumps(validation["preferred_unsound"], ensure_ascii=False)
        )
    if validation.get("preferred_incomplete"):
        msg.append(
            "INCOMPLETE: a paired run has equal outputs, but the guard rejects it: "
            + json.dumps(validation["preferred_incomplete"], ensure_ascii=False)
        )
    msg.append(
        "Refine the relational semantic explanation or its applicability guard. "
        "Do not enumerate or guess source-operation subsets. "
        "The verifier has only checked finite-domain executions, not proved the formula. "
        "Respond in JSON with revised mask_guard and observer_relations."
    )
    return "\n".join(msg)


def run_trial(*, provider, model, endpoint, mode, rounds, num_ctx, timeout,
              seed, source, output_dir, mock=False):
    original, without_a, target_line = make_versions(source)
    conversations = [{"role": "system", "content": SYSTEM}]
    exchanges, stats = [], []
    if mode == "generic":
        if mock:
            summary_text = '{"functions": "mock-only generic summary"}'
            summary_stats = {"mock": True}
        else:
            summary_text, summary_stats = raw_chat_request(
                provider, model,
                [{"role": "system", "content": "Return concise JSON."},
                 {"role": "user", "content": generic_summary_prompt(source)}],
                endpoint, 0, seed, num_ctx, timeout
            )
        exchanges.append({"phase": "generic_summary", "content": summary_text,
                          "stats": summary_stats})
        stats.append(summary_stats)
    else:
        summary_text = ""

    conversations.append({"role": "user", "content": make_prompt(
        mode, source, target_line, summary_text
    )})
    final_validation, final_candidate = None, None
    for round_id in range(1, rounds + 1):
        if mock:
            # Only tests the runner; never label these outputs as Qwen results.
            guard = ("pre or (use_left and use_right)" if round_id == 1 else
                     "pre or ((use_left or xs[0] == min(xs)) and "
                     "(use_right or xs[-1] == max(xs)))")
            content = json.dumps({"target_effect": "MOCK ONLY",
                                  "observer_relations": [], "mask_guard": guard,
                                  "uncertainty": "MOCK ONLY"})
            step_stats = {"mock": True}
        else:
            content, step_stats = raw_chat_request(
                provider, model, conversations, endpoint, 0, seed, num_ctx, timeout
            )
        stats.append(step_stats)
        valid_json_error = ""
        try:
            parsed = parse_model_json(content)
            candidate = parsed["mask_guard"].strip()
            validation = guard_report(original, without_a, candidate)
        except (ValueError, json.JSONDecodeError) as exc:
            parsed, candidate = None, None
            valid_json_error = str(exc)
            validation = {"invalid_json": valid_json_error}

        exchanges.append({"phase": "guard_proposal", "round": round_id,
                          "response": content, "parsed": parsed,
                          "validation": validation, "stats": step_stats})
        final_validation, final_candidate = validation, candidate
        conversations.append({"role": "assistant", "content": content})
        if (candidate is not None and validation.get("soundness_counterexamples") == 0
                and validation.get("completeness_counterexamples") == 0
                and "invalid_guard" not in validation):
            break
        if round_id < rounds:
            conversations.append({"role": "user", "content": feedback_text(
                candidate, validation, valid_json_error
            )})

    result = {
        "is_mock": mock, "provider": provider, "model": model, "mode": mode,
        "source_sha256": hashlib.sha256(source.encode()).hexdigest(),
        "source": source, "target_A_line": target_line,
        "finite_domain": "nonempty xs length 1..5 over [-1,0,1,2]; 3 booleans",
        "temperature": 0, "seed": seed, "num_ctx": num_ctx,
        "exchanges": exchanges, "final_candidate": final_candidate,
        "final_validation": final_validation,
        "source_attribution_verified": False,
        "observer_contracts_formally_verified": False,
        "notes": "Only the final Boolean guard has been bounded-checked; this is not a proof.",
        "generated_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
    }
    out = output_dir / f"{mode}_seed{seed}.json"
    out.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    return result, out


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--provider", choices=["ollama", "dashscope"], default="ollama")
    p.add_argument("--model", default="qwen2.5-coder:7b")
    p.add_argument("--endpoint", default=None)
    p.add_argument("--mode", choices=["direct", "generic", "target", "all"], default="target")
    p.add_argument("--max-rounds", type=int, default=3)
    p.add_argument("--num-ctx", type=int, default=8192)
    p.add_argument("--timeout", type=int, default=300)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--output", type=Path, default=Path("mace_runs"))
    p.add_argument("--source-names", action="store_true",
                   help="Keep descriptive helper names (default: anonymize them)")
    p.add_argument("--smoke", action="store_true", help="CPU-only validator self-check")
    p.add_argument("--mock", action="store_true",
                   help="CPU-only fake model response; NOT an LLM experiment")
    args = p.parse_args(argv)
    if args.max_rounds < 1 or args.max_rounds > 10:
        p.error("--max-rounds must be 1..10")
    if args.provider == "ollama":
        endpoint = args.endpoint or "http://127.0.0.1:11434"
    else:
        endpoint = args.endpoint or os.getenv(
            "DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"
        )
    source = PROGRAM_SOURCE if args.source_names else obfuscate_function_names(PROGRAM_SOURCE)
    original, deleted, target_line = make_versions(source)
    if args.smoke:
        guards = [
            "pre or (use_left and use_right)",
            "pre or ((use_left or xs[0] == min(xs)) and "
            "(use_right or xs[-1] == max(xs)))"
        ]
        for i, guard in enumerate(guards):
            print(f"CPU-SMOKE case {i}: {json.dumps(guard_report(original, deleted, guard), ensure_ascii=False)}")
        return 0
    args.output.mkdir(parents=True, exist_ok=True)
    modes = ["direct", "generic", "target"] if args.mode == "all" else [args.mode]
    summary = []
    for mode in modes:
        result, out = run_trial(
            provider=args.provider, model=args.model, endpoint=endpoint,
            mode=mode, rounds=args.max_rounds, num_ctx=args.num_ctx,
            timeout=args.timeout, seed=args.seed, source=source,
            output_dir=args.output, mock=args.mock
        )
        v = result["final_validation"] or {}
        item = {"mode": mode, "model": args.model, "mock": args.mock,
                "guard": result["final_candidate"],
                "unsound": v.get("soundness_counterexamples"),
                "incomplete": v.get("completeness_counterexamples"),
                "invalid": v.get("invalid_guard") or v.get("invalid_json"),
                "rounds": sum(1 for x in result["exchanges"] if x["phase"] == "guard_proposal"),
                "log": str(out)}
        summary.append(item)
        print(json.dumps(item, ensure_ascii=False))
    path = args.output / "summary.json"
    path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print("RESULTS:", str(args.output.resolve()))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError) as exc:
        print("ERROR:", str(exc), file=sys.stderr)
        raise SystemExit(2)
