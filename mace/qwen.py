"""Local Qwen client (Ollama by default, DashScope-compatible fallback).

Only the model service is contacted, and only on localhost for Ollama.
Every call returns the raw text, token counts, wall-clock time and the model
identity so that the experiment log can be audited afterwards.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Dict, List

DEFAULT_OLLAMA = "http://127.0.0.1:11434"
DEFAULT_DASHSCOPE = "https://dashscope.aliyuncs.com/compatible-mode/v1"


class ModelError(RuntimeError):
    pass


@dataclass
class Response:
    content: str
    stats: Dict[str, Any] = field(default_factory=dict)
    request_messages: List[Dict[str, str]] = field(default_factory=list)


def extract_json(text: str) -> Dict[str, Any]:
    """Pull the first JSON object out of a model response."""
    if not isinstance(text, str) or not text.strip():
        raise ValueError("empty model response")
    body = text.strip()
    if body.startswith("```"):
        body = body.split("\n", 1)[1] if "\n" in body else body
        if body.rstrip().endswith("```"):
            body = body.rstrip()[:-3]
    decoder = json.JSONDecoder()
    for index, char in enumerate(body):
        if char != "{":
            continue
        try:
            obj, _ = decoder.raw_decode(body[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            return obj
    raise ValueError("response contains no JSON object")


class QwenClient:
    def __init__(self, provider: str = "ollama", model: str = "qwen2.5-coder:7b",
                 endpoint: str | None = None, num_ctx: int = 8192,
                 num_predict: int = 4096, temperature: float = 0.0,
                 seed: int = 42, timeout: int = 300, retries: int = 2):
        self.provider = provider
        self.model = model
        self.endpoint = (endpoint or (DEFAULT_OLLAMA if provider == "ollama" else DEFAULT_DASHSCOPE)).rstrip("/")
        self.num_ctx = num_ctx
        self.num_predict = num_predict
        self.temperature = temperature
        self.seed = seed
        self.timeout = timeout
        self.retries = retries
        self.calls: List[Dict[str, Any]] = []

    # -- transport --------------------------------------------------------
    def _post(self, path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        url = self.endpoint + path
        headers = {"Content-Type": "application/json"}
        if self.provider != "ollama":
            key = os.environ.get("DASHSCOPE_API_KEY", "")
            if not key:
                raise ModelError("DASHSCOPE_API_KEY is not set on this machine")
            headers["Authorization"] = "Bearer " + key
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(url, data=data, headers=headers, method="POST")
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            return json.loads(response.read().decode("utf-8"))

    def chat(self, messages: List[Dict[str, str]], *, purpose: str = "contract",
             json_mode: bool = True) -> Response:
        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            start = time.perf_counter()
            try:
                if self.provider == "ollama":
                    payload = {
                        "model": self.model, "messages": messages, "stream": False,
                        "format": "json" if json_mode else "",
                        "options": {"temperature": self.temperature, "seed": self.seed,
                                    "num_ctx": self.num_ctx,
                                    "num_predict": self.num_predict},
                    }
                    body = self._post("/api/chat", payload)
                    content = body.get("message", {}).get("content", "")
                    stats = {
                        "prompt_tokens": body.get("prompt_eval_count"),
                        "completion_tokens": body.get("eval_count"),
                        "total_duration_ns": body.get("total_duration"),
                        "load_duration_ns": body.get("load_duration"),
                        "prompt_eval_duration_ns": body.get("prompt_eval_duration"),
                        "eval_duration_ns": body.get("eval_duration"),
                        "model": body.get("model"),
                        "done_reason": body.get("done_reason"),
                    }
                else:
                    payload = {"model": self.model, "messages": messages,
                               "temperature": self.temperature,
                               "response_format": {"type": "json_object"} if json_mode else None}
                    payload = {k: v for k, v in payload.items() if v is not None}
                    body = self._post("/chat/completions", payload)
                    content = body["choices"][0]["message"]["content"]
                    stats = {"usage": body.get("usage", {}), "model": body.get("model")}
                stats["wall_seconds"] = round(time.perf_counter() - start, 3)
                stats["attempt"] = attempt
                record = {"purpose": purpose, "messages": messages, "stats": stats,
                          "response": content, "model": self.model, "provider": self.provider}
                self.calls.append(record)
                if not content or not content.strip():
                    raise ModelError("empty completion")
                return Response(content=content, stats=stats, request_messages=messages)
            except (urllib.error.URLError, ModelError, TimeoutError) as exc:
                last_error = exc
                time.sleep(1.5 * (attempt + 1))
        raise ModelError(f"model call failed after {self.retries + 1} attempts: {last_error}")

    def model_info(self) -> Dict[str, Any]:
        if self.provider != "ollama":
            return {"provider": self.provider, "model": self.model}
        try:
            request = urllib.request.Request(
                self.endpoint + "/api/show",
                data=json.dumps({"model": self.model}).encode("utf-8"),
                headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(request, timeout=30) as response:
                body = json.loads(response.read().decode("utf-8"))
            return {"provider": self.provider, "model": self.model,
                    "details": body.get("details", {}),
                    "parameters": body.get("parameters", "")}
        except Exception as exc:  # noqa: BLE001 - metadata is best effort
            return {"provider": self.provider, "model": self.model, "error": str(exc)}

    def runtime_ps(self) -> Any:
        if self.provider != "ollama":
            return None
        try:
            with urllib.request.urlopen(self.endpoint + "/api/ps", timeout=15) as response:
                return json.loads(response.read().decode("utf-8"))
        except Exception:  # noqa: BLE001
            return None
