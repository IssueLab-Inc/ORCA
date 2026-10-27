"""Thin client for Meta's models over an OpenAI-style chat completions endpoint.

Configuration comes from the environment so the same code talks to the Meta Model API (Muse Spark)
or a partner host for the open-weights models (Baseten: meta-models/muse-spark-open):

    META_API_BASE_URL   https://api.meta.ai/v1 (requests go to <base>/chat/completions)
    META_API_KEY
    META_MODEL          muse-spark-1.3-contributor
    META_REASONING_EFFORT  low (default) | minimal | medium | high | "" for the API's default. Muse Spark reasons
                        before answering; on Northbank "low" cut a proposal from ~58 s to ~23 s (evals/README.md).

Bulk triage can run on a different host (`triage_model`):

    TRIAGE_API_KEY      (or BASETEN_API_KEY) turns it on; without one, triage uses Muse Spark above
    TRIAGE_API_BASE_URL https://inference.baseten.co/v1
    TRIAGE_MODEL        meta-models/muse-spark-open
    TRIAGE_IMAGES       1 (default) sends the clash images; 0 for a text-only host

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


def _strip_fence(raw: str) -> str:
    """Some hosts wrap JSON mode replies in a ```json fence."""
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
        raw = raw.rsplit("```", 1)[0]
    return raw


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
        self.strict = True  # cleared when the host rejects json_schema; then plain JSON mode is used

    def _post(self, payload: dict) -> dict:
        r = self.client.post(f"{self.base_url}/chat/completions", json=payload,
                             headers={"Authorization": f"Bearer {self.api_key}"})
        r.raise_for_status()
        return r.json()

    def complete_json(self, system: str, text: str, images: list[Path] | None = None,
                      schema: dict | None = None) -> dict:
        """`schema` turns on strict structured output (`json_schema`); without it the reply is any JSON object."""
        content = [{"type": "text", "text": text}] + [_image_part(p) for p in images or []]
        strict = bool(schema) and self.strict
        if schema and not strict:
            system += "\n\nReply with one JSON object matching this schema:\n" + json.dumps(schema)
        response_format = ({"type": "json_schema", "json_schema": {"name": "reply", "schema": schema, "strict": True}}
                           if strict else {"type": "json_object"})
        payload = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": content}],
            "response_format": response_format,
            "temperature": 0.2,
            **({"reasoning_effort": self.reasoning_effort} if self.reasoning_effort else {}),
        }
        try:
            body = self._post(payload)
        except httpx.HTTPStatusError as e:
            if strict and e.response.status_code in (400, 422):  # host without structured output: JSON mode
                self.strict = False
                return self.complete_json(system, text, images, schema)
            raise
        raw = body["choices"][0]["message"]["content"]
        return json.loads(_strip_fence(raw))

    def chat(self, messages: list[dict], tools: list[dict]) -> dict:
        """One assistant turn with tools: returns the message (content and/or tool_calls)."""
        body = self._post({
            "model": self.model, "messages": messages, "tools": tools, "temperature": 0.2,
            **({"reasoning_effort": self.reasoning_effort} if self.reasoning_effort else {}),
        })
        return body["choices"][0]["message"]


def triage_model(timeout_s: float = 120) -> tuple[MetaChatModel, dict]:
    """The model for bulk triage and a description of it for the UI.

    Muse Spark Open on Baseten (or any OpenAI-compatible host) when TRIAGE_API_KEY / BASETEN_API_KEY is set,
    otherwise Muse Spark on Meta's API."""
    load_env()
    key = os.environ.get("TRIAGE_API_KEY") or os.environ.get("BASETEN_API_KEY")
    images = os.environ.get("TRIAGE_IMAGES", "1") != "0"
    if key:
        model = MetaChatModel(os.environ.get("TRIAGE_API_BASE_URL", "https://inference.baseten.co/v1"), key,
                              os.environ.get("TRIAGE_MODEL", "meta-models/muse-spark-open"), timeout_s,
                              reasoning_effort=os.environ.get("TRIAGE_REASONING_EFFORT", ""))
        return model, {"model": model.model, "open_weights": True, "images": images}
    model = MetaChatModel(timeout_s=timeout_s)
    return model, {"model": model.model, "open_weights": False, "images": True,
                   "note": "No open-weights host configured (TRIAGE_API_KEY); using Muse Spark."}
