# MACE: local Qwen pilot (2026-10-29)

The kit contains:
- `mace_semantic_core_poc.py` — paired Python program and bounded checker
- `mace_qwen_pilot.py` — Qwen request, JSON extraction, bounded validation, feedback rounds, and baseline modes
- `mace_qwen_obligation.json` — original standalone obligation from the earlier prototype

## A. What you need to do once on the GPU machine

Start a Linux GPU instance (RTX 4090 24 GB or A100 40 GB), verify the driver:

```bash
nvidia-smi
```

If Ollama is not installed, use the official installation instructions at https://docs.ollama.com/linux . Example:

```bash
curl -fsSL https://ollama.com/install.sh | sh
```

Start Ollama if the installation has not already started its service:

```bash
ollama serve
```

Run that in one terminal and use a second terminal for the following commands. When Ollama is already running as a system service, **do not start a second server**.

Download a light model for the initial feasibility check:

```bash
ollama pull qwen2.5-coder:7b
ollama list
```

The official Ollama registry lists this model at approximately 4.7 GB. The GPU needs additional VRAM for context and runtime overhead. If this model has difficulty deriving the constraints, an optional stronger test is:

```bash
ollama pull qwen3-coder:30b
```

The latter is approximately 19 GB in the Ollama Q4_K_M package; on a 24 GB RTX 4090 this leaves limited headroom for KV cache. Keep context small initially, and check whether it is running on GPU:

```bash
ollama ps
nvidia-smi
```

If model downloads are blocked from your network, avoid renting a GPU merely while retrying downloads; use a reachable provider/model mirror, or the alternative API path below.

## B. Put both Python files into the same directory, then run

```bash
python3 mace_qwen_pilot.py --smoke
python3 mace_qwen_pilot.py --provider ollama --model qwen2.5-coder:7b --mode target --max-rounds 3
```

- `--smoke`: CPU-only check. The expected second candidate has 0 soundness and 0 completeness counterexamples on the bounded fixture domain.
- `--mode target`: **real Qwen** receives only the program plus the marked A, derives a Boolean guard, receives a bounded counterexample, and can revise the guard.
- Default helper names are obfuscated as `fn_0`, `fn_1`, etc., to prevent reliance on function names.
- The evaluator does **not** pre-label masking sites B1/B2 in the Qwen input.

Then run baseline variants with the **same installed model**:

```bash
python3 mace_qwen_pilot.py --provider ollama --model qwen2.5-coder:7b --mode all --max-rounds 3
```

The modes are `direct`, `generic`, and `target`. The generic method makes an extra summary call; log token counts and costs before claiming fair efficiency comparisons. All modes operate on the same bounded source fixture. Repeating with multiple seeds and independent unseen programs is essential for a scientific evaluation.

Once the small model is working, optionally evaluate:

```bash
python3 mace_qwen_pilot.py --provider ollama --model qwen3-coder:30b --mode all --num-ctx 4096 --max-rounds 3
```

The longer model may require reduced context or an A100 if it doesn't fit in available VRAM. `--num-ctx 4096` is a conservative pilot setting, not a maximum for future research.

## C. Alternative: Qwen cloud API, no local GPU

If you choose Alibaba Cloud Bailian / DashScope instead, create your own API key and keep it on your machine. For a Linux shell:

```bash
export DASHSCOPE_API_KEY='YOUR_LOCAL_SECRET'
python3 mace_qwen_pilot.py --provider dashscope --model qwen-plus --mode target
```

The default API URL is `https://dashscope.aliyuncs.com/compatible-mode/v1`, a documented region-specific option. The `qwen-plus` model ID is an example, not a guarantee of current availability in your specific workspace. Use the model actually available in your account. Your key must never appear in a screenshot, result log, Git repository or chat message. If using a workspace-specific endpoint, set `DASHSCOPE_BASE_URL` locally.

## D. What to share back for analysis

Upload the files from `mace_runs/`, especially `summary.json` and `target_seed42.json`. These contain the source fixture, generated expressions, verifier feedback, timings and model identity, **not** an API key.

Do not share a private repository's source without authorization. The pilot does not collect secrets, but generated explanations can contain code snippets.

## E. Critical limitations

1. This does not claim a formal proof; the checker enumerates **10,912 paired executions**, length 1..5 with integers from {-1,0,1,2} and three Booleans.
2. Only Boolean output-equivalence guards are checked automatically. Qwen's semantic explanations and source provenance are recorded but NOT yet independently verified.
3. The current fixture is constructed and simple. To validate an ICPC claim, use unseen real functions and stronger baselines.
4. No remote GPU login, service deployment, or model inference has been performed by the assistant on your rented machine.
5. The Python program inside this kit is a trusted research fixture and uses `exec` to compile the two program versions. Never use it to execute arbitrary untrusted repository code without separate process isolation.
