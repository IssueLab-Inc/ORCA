"""Thin client for Meta's models over an OpenAI-style chat completions endpoint.

Configuration comes from the environment so the same code talks to the Meta Model API (Muse Spark)
or a partner host for the open-weights models (Baseten: meta-models/muse-spark-open-1026):

    META_API_BASE_URL   https://api.meta.ai/v1 (requests go to <base>/chat/completions)
    META_API_KEY
    META_MODEL          muse-spark-1.3-contributor
    META_REASONING_EFFORT  low (default) | minimal | medium | high | "" for the API's default. Muse Spark reasons
                        before answering; on Northbank "low" cut a proposal from ~58 s to ~23 s (evals/README.md).

Check the request shape against the Meta Model API quickstart on day 1; only `_post` should need to change.
"""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path
from typing import Protocol

import httpx


ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


def load_env(path: Path = ENV_FILE) -> None:
    """Read KEY=value lines from the repo's .env into the environment; real environment variables win."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        key, sep, value = line.partition("=")
        if sep and key.strip() and not key.lstrip().startswith("#"):
            os.environ.setdefault(key.strip(), value.strip())


class ChatModel(Protocol):
    def complete_json(self, system: str, text: str, images: list[Path] | None = None) -> dict: ...


class ToolModel(Protocol):
    def chat(self, messages: list[dict], tools: list[dict]) -> dict: ...


def image_part(path: Path) -> dict:
    """An image as an OpenAI-style content part (base64 data URL)."""
    return _image_part(path)


def _image_part(path: Path) -> dict:
    mime = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
    data = base64.b64encode(path.read_bytes()).decode()
    return {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{data}"}}


class MetaChatModel:
    def __init__(self, base_url: str | None = None, api_key: str | None = None, model: str | None = None,
                 timeout_s: float = 120, reasoning_effort: str | None = None):
        load_env()
        self.base_url = (base_url or os.environ.get("META_API_BASE_URL", "https://api.meta.ai/v1")).rstrip("/")
        self.api_key = api_key or os.environ["META_API_KEY"]
        self.model = model or os.environ.get("META_MODEL", "muse-spark-1.3-contributor")
        self.reasoning_effort = (reasoning_effort if reasoning_effort is not None
                                 else os.environ.get("META_REASONING_EFFORT", "low"))
        self.client = httpx.Client(timeout=timeout_s)

    def _post(self, payload: dict) -> dict:
        r = self.client.post(f"{self.base_url}/chat/completions", json=payload,
                             headers={"Authorization": f"Bearer {self.api_key}"})
        r.raise_for_status()
        return r.json()

    def complete_json(self, system: str, text: str, images: list[Path] | None = None,
                      schema: dict | None = None) -> dict:
        """`schema` turns on strict structured output (`json_schema`); without it the reply is any JSON object."""
        content = [{"type": "text", "text": text}] + [_image_part(p) for p in images or []]
        response_format = ({"type": "json_schema", "json_schema": {"name": "reply", "schema": schema, "strict": True}}
                           if schema else {"type": "json_object"})
        body = self._post({
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": content}],
            "response_format": response_format,
            "temperature": 0.2,
            **({"reasoning_effort": self.reasoning_effort} if self.reasoning_effort else {}),
        })
        raw = body["choices"][0]["message"]["content"]
        return json.loads(raw)

    def chat(self, messages: list[dict], tools: list[dict]) -> dict:
        """One assistant turn with tools: returns the message (content and/or tool_calls)."""
        body = self._post({
            "model": self.model, "messages": messages, "tools": tools, "temperature": 0.2,
            **({"reasoning_effort": self.reasoning_effort} if self.reasoning_effort else {}),
        })
        return body["choices"][0]["message"]
