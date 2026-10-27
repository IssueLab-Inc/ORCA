"""Thin client for Meta's models over an OpenAI-style chat completions endpoint.

Configuration comes from the environment so the same code talks to the Meta Model API (Muse Spark)
or a partner host for the open-weights models (Baseten: meta-models/muse-spark-open-1026):

    META_API_BASE_URL   e.g. the Meta Model API base URL from its quickstart
    META_API_KEY
    META_MODEL          e.g. muse-spark-1.3

Check the request shape against the Meta Model API quickstart on day 1; only `_post` should need to change.
"""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path
from typing import Protocol

import httpx


class ChatModel(Protocol):
    def complete_json(self, system: str, text: str, images: list[Path] | None = None) -> dict: ...


def _image_part(path: Path) -> dict:
    mime = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
    data = base64.b64encode(path.read_bytes()).decode()
    return {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{data}"}}


class MetaChatModel:
    def __init__(self, base_url: str | None = None, api_key: str | None = None, model: str | None = None,
                 timeout_s: float = 120):
        self.base_url = (base_url or os.environ["META_API_BASE_URL"]).rstrip("/")
        self.api_key = api_key or os.environ["META_API_KEY"]
        self.model = model or os.environ.get("META_MODEL", "muse-spark-1.3")
        self.client = httpx.Client(timeout=timeout_s)

    def _post(self, payload: dict) -> dict:
        r = self.client.post(f"{self.base_url}/chat/completions", json=payload,
                             headers={"Authorization": f"Bearer {self.api_key}"})
        r.raise_for_status()
        return r.json()

    def complete_json(self, system: str, text: str, images: list[Path] | None = None) -> dict:
        content = [{"type": "text", "text": text}] + [_image_part(p) for p in images or []]
        body = self._post({
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": content}],
            "response_format": {"type": "json_object"},
            "temperature": 0.2,
        })
        raw = body["choices"][0]["message"]["content"]
        return json.loads(raw)
