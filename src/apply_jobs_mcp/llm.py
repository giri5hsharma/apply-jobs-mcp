"""Minimal Ollama client (stdlib urllib only).

Learning notes:
- Ollama exposes a local HTTP API at /api/chat; we send a system+user
  message and read back the text. No API keys, no SDK, everything local.
- Errors raise LLMError so callers can fall back to templates.
"""
from __future__ import annotations

import json
import urllib.request

from .config import Config


class LLMError(Exception):
    pass


def chat(cfg: Config, system: str, user: str, timeout: float = 180.0) -> str:
    if not cfg.llm.get("enabled", False):
        raise LLMError("LLM disabled in config (llm.enabled = false)")
    endpoint = cfg.llm.get("endpoint", "http://127.0.0.1:11434")
    model = cfg.llm.get("model", "gemma4:31b-cloud")
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "stream": False,
        "options": {"temperature": 0.4},
    }
    req = urllib.request.Request(
        endpoint.rstrip("/") + "/api/chat",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode())
    except Exception as e:
        raise LLMError(str(e)) from e
    content = data.get("message", {}).get("content", "").strip()
    if not content:
        raise LLMError("empty response from model")
    return content
