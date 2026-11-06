"""Local Qwen client for executability runs.

This is a transport adapter only.  It loads a Hugging Face ``Qwen2.5-Coder``
checkpoint with ``transformers`` and exposes the same ``chat``/``model_info``
surface that ``mace.loop`` expects from ``mace.qwen.QwenClient``.  It does not
change prompts, verifiers, or any MACE algorithm.

The model directory is passed explicitly; no API key is read or logged.
"""
from __future__ import annotations

import time
from typing import Any, Dict, List

from mace.qwen import Response


class LocalQwenClient:
    provider = "transformers-local"

    def __init__(self, model_path: str, *, max_new_tokens: int = 1024,
                 temperature: float = 0.0, seed: int = 42,
                 device: str = "cuda", timeout: int = 600):
        self.model_path = model_path
        self.model_name = model_path.rstrip("/\\").split("/")[-1].split("\\")[-1]
        # ``mace.loop`` records ``client.model`` in run metadata; keep the same
        # surface as ``mace.qwen.QwenClient``.
        self.model = self.model_name
        self.max_new_tokens = max_new_tokens
        self.temperature = temperature
        self.seed = seed
        self.device = device
        self.timeout = timeout
        self.calls: List[Dict[str, Any]] = []
        self._model = None
        self._tokenizer = None

    def _load(self) -> None:
        if self._model is not None:
            return
        import torch  # noqa: PLC0415
        from transformers import AutoModelForCausalLM, AutoTokenizer  # noqa: PLC0415

        self._tokenizer = AutoTokenizer.from_pretrained(
            self.model_path, local_files_only=True, trust_remote_code=False)
        self._model = AutoModelForCausalLM.from_pretrained(
            self.model_path, local_files_only=True, trust_remote_code=False,
            dtype=torch.bfloat16, attn_implementation="sdpa")
        self._model.to(self.device)
        self._model.eval()

    def chat(self, messages: List[Dict[str, str]], *, purpose: str = "contract",
             json_mode: bool = True) -> Response:
        import torch  # noqa: PLC0415

        self._load()
        assert self._tokenizer is not None and self._model is not None
        torch.manual_seed(self.seed)
        start = time.perf_counter()
        text = self._tokenizer.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True)
        inputs = self._tokenizer([text], return_tensors="pt").to(self._model.device)
        prompt_tokens = int(inputs["input_ids"].shape[1])
        generation = {
            "max_new_tokens": self.max_new_tokens,
            "do_sample": False,
            "pad_token_id": self._tokenizer.eos_token_id,
        }
        if self.temperature and self.temperature > 0:
            generation.update({"do_sample": True, "temperature": self.temperature,
                               "top_p": 0.9})
        with torch.inference_mode():
            output = self._model.generate(**inputs, **generation)
        completion_ids = output[0][prompt_tokens:]
        content = self._tokenizer.decode(completion_ids, skip_special_tokens=True)
        wall = round(time.perf_counter() - start, 3)
        stats = {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": int(completion_ids.shape[0]),
            "total_tokens": prompt_tokens + int(completion_ids.shape[0]),
            "wall_seconds": wall,
            "model": self.model_name,
            "provider": self.provider,
            "temperature": self.temperature,
            "seed": self.seed,
            "max_new_tokens": self.max_new_tokens,
            "device": str(self._model.device),
        }
        self.calls.append({"purpose": purpose, "messages": messages,
                           "stats": stats, "response": content,
                           "model": self.model_name, "provider": self.provider})
        return Response(content=content, stats=stats, request_messages=messages)

    def model_info(self) -> Dict[str, Any]:
        self._load()
        assert self._model is not None
        return {
            "provider": self.provider,
            "model": self.model_name,
            "path": self.model_path,
            "dtype": str(next(self._model.parameters()).dtype),
            "device": str(self._model.device),
            "parameters": sum(p.numel() for p in self._model.parameters()),
            "max_position_embeddings": getattr(self._model.config,
                                               "max_position_embeddings", None),
        }

    def runtime_ps(self) -> Any:
        if self._model is None:
            return None
        import torch  # noqa: PLC0415
        if torch.cuda.is_available():
            return {"allocated_bytes": int(torch.cuda.memory_allocated()),
                    "reserved_bytes": int(torch.cuda.memory_reserved())}
        return None
