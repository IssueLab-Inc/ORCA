"""Thin client for Meta's models over an OpenAI-style chat completions endpoint.

Configuration comes from the environment so the same code talks to the Meta Model API (Muse Spark)
or a partner host for the open-weights models (Baseten: meta-models/muse-spark-open):

    META_API_BASE_URL   https://api.meta.ai/v1 (requests go to <base>/chat/completions)
    META_API_KEY
    META_MODEL          muse-spark-1.3-contributor
    META_REASONING_EFFORT  low (default) | minimal | medium | high | "" for the API's default. Muse Spark reasons
                        before answering; on Northbank "low" cut a proposal from ~58 s to ~23 s (evals/README.md).

A clash Muse Spark finds no verified fix for can go to a larger model for a second, longer try (`escalation_model`,
docs/escalation.md). It bills every token, so each call's usage is counted and charged to the day's limit (spend.py):

    META_ESCALATION_MODEL   muse-wonder-1.0
    META_ESCALATION_EFFORT  medium (default) | minimal | low | high

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
import threading
from pathlib import Path
from typing import Callable, Protocol

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


# Models billed per token on the Meta Model API, by id prefix (any Muse Wonder version): USD per input and per output
# token (reasoning counts as output). Muse Spark's contributor tier and the open-weights host are not counted here.
# SIGHTLINE_MODEL_PRICES adds or replaces prices: a JSON object of id prefix → [USD per million input tokens, per
# million output tokens], for another host's models.
PRICES = {"muse-wonder": (4 / 1e6, 20 / 1e6)}
FIXED_EFFORT = ("judge",)   # roles whose effort is their own, whatever the owner or everyone's settings say
# Names people read, by id prefix (the longest prefix that matches wins). SIGHTLINE_MODEL_LABELS adds or replaces
# them: a JSON object of id prefix → name.
LABELS = {"muse-wonder": "Muse Wonder", "muse-spark": "Muse Spark", "meta-models/muse-spark-open": "Muse Spark Open",
          "muse-spark-open": "Muse Spark Open", "muse-image": "Muse Image", "muse-voice": "Muse Voice",
          "muse-voice-transcribe": "Muse Voice Transcribe"}
# The model each role runs on, when its env var is unset.
DEFAULT_MODELS = {"proposal": ("META_MODEL", "muse-spark-1.3-contributor"),
                  "escalation": ("META_ESCALATION_MODEL", "muse-wonder-1.0"),
                  "image": ("META_IMAGE_MODEL", "muse-image-1.0"),
                  "voice": ("META_VOICE_MODEL", "muse-voice-transcribe-1.0")}


def _env_float(name: str, default: float) -> float:
    """A number from the environment (limits.env_float, here without importing the app's limits)."""
    from .limits import env_float
    return env_float(name, default)


def _env_json(name: str) -> dict:
    """A JSON object from the environment, or {} (unset, empty or not an object)."""
    try:
        value = json.loads(os.environ.get(name) or "{}")
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}


def _longest(table: dict, model_id: str):
    return next((table[p] for p in sorted(table, key=len, reverse=True) if model_id.startswith(p)), None)


def model_id(role: str) -> str:
    """The model id a role runs on (`DEFAULT_MODELS`, its env var first)."""
    load_env()
    var, default = DEFAULT_MODELS[role]
    return os.environ.get(var) or default


def model_label(model_id: str) -> str:
    """A model's name as people read it ("Muse Wonder"), from its id (`LABELS`, `SIGHTLINE_MODEL_LABELS`)."""
    labels = {**LABELS, **{str(k): str(v) for k, v in _env_json("SIGHTLINE_MODEL_LABELS").items()}}
    return _longest(labels, model_id) or model_id


def labels() -> dict:
    """The name of the model behind each role, for the page: proposal, escalation, triage, image, voice."""
    return {**{role: model_label(model_id(role)) for role in DEFAULT_MODELS},
            "triage": model_label(triage_model_info()["model"])}


class Usage:
    """Tokens a model's calls used (both endpoints' shapes), and what they cost when the model is priced."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.calls = self.input_tokens = self.output_tokens = self.reasoning_tokens = 0

    @staticmethod
    def of(raw: dict | None) -> tuple[int, int, int]:
        """(input, output, reasoning) tokens from a chat completions or a Responses `usage`."""
        raw = raw or {}
        details = raw.get("completion_tokens_details") or raw.get("output_tokens_details") or {}
        return (int(raw.get("prompt_tokens", raw.get("input_tokens", 0)) or 0),
                int(raw.get("completion_tokens", raw.get("output_tokens", 0)) or 0),
                int(details.get("reasoning_tokens", 0) or 0))

    def add(self, raw: dict | None) -> tuple[int, int, int]:
        tokens = self.of(raw)
        with self._lock:
            self.calls += 1
            self.input_tokens += tokens[0]
            self.output_tokens += tokens[1]
            self.reasoning_tokens += tokens[2]
        return tokens

    def snapshot(self) -> tuple[int, int, int, int]:
        with self._lock:
            return self.calls, self.input_tokens, self.output_tokens, self.reasoning_tokens

    def as_dict(self, model_id: str, since: tuple[int, int, int, int] = (0, 0, 0, 0)) -> dict:
        """The usage (since a `snapshot`, for one run on a model other runs share), and what it cost."""
        calls, tin, tout, reasoning = (now - then for now, then in zip(self.snapshot(), since))
        return {"model": model_id, "calls": calls, "input_tokens": tin, "output_tokens": tout,
                "reasoning_tokens": reasoning, "usd": round(cost(model_id, tin, tout), 4)}


def prices() -> dict:
    """`PRICES` with `SIGHTLINE_MODEL_PRICES` over them, USD per token."""
    extra = {}
    for prefix, p in _env_json("SIGHTLINE_MODEL_PRICES").items():
        try:
            extra[str(prefix)] = (float(p[0]) / 1e6, float(p[1]) / 1e6)
        except (TypeError, ValueError, IndexError):
            continue
    return {**PRICES, **extra}


def cost(model_id: str, input_tokens: int, output_tokens: int) -> float:
    """What a call cost in USD (0 for a model not billed per token here)."""
    price_in, price_out = _longest(prices(), model_id) or (0.0, 0.0)
    return input_tokens * price_in + output_tokens * price_out


class ChatModel(Protocol):
    def complete_json(self, system: str, text: str, images: list[Path] | None = None) -> dict: ...


class ToolModel(Protocol):
    def chat(self, messages: list[dict], tools: list[dict], *, timeout_s: float | None = None) -> dict: ...


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
                 timeout_s: float | None = None, reasoning_effort: str | None = None):
        load_env()
        if timeout_s is None:   # how long one model call may take (SIGHTLINE_MODEL_TIMEOUT_S)
            timeout_s = _env_float("SIGHTLINE_MODEL_TIMEOUT_S", 120)
        self.base_url = (base_url or os.environ.get("META_API_BASE_URL", "https://api.meta.ai/v1")).rstrip("/")
        self.api_key = api_key or os.environ["META_API_KEY"]
        self.model = model or model_id("proposal")
        self.reasoning_effort = (reasoning_effort if reasoning_effort is not None
                                 else os.environ.get("META_REASONING_EFFORT", "low"))
        self.role = "default"  # "triage" / "escalation": the owner and settings set their effort separately
        self.client = httpx.Client(timeout=timeout_s)
        self.usage = Usage()
        # Hears each call's cost in USD as it lands (the escalation charges the day's limit with it, spend.py).
        self.on_cost: Callable[[float], None] | None = None
        self.strict = True  # cleared when the host rejects json_schema; then plain JSON mode is used
        # Meta's Responses endpoint streams reasoning summaries (short notes on what the model is working out), which
        # the UI shows while the agent thinks. Cleared if the host does not offer it; chat completions are used then.
        # META_STREAMS_REASONING: "1" or "0" says so for any host; unset, Meta's own host is assumed to.
        streams = os.environ.get("META_STREAMS_REASONING", "").strip()
        self.streams_reasoning = streams == "1" if streams in ("0", "1") else "api.meta.ai" in self.base_url

    @property
    def effort(self) -> str | None:
        """The owner's effort for this request (owner.py), else the one set for everyone (settings.py), else this model's."""
        from . import owner, settings
        if self.role in FIXED_EFFORT:   # a check measured at its own effort (Show it built's judges): no setting moves it
            return self.reasoning_effort
        return owner.effort(self.role) or settings.effort_for(self.role) or self.reasoning_effort

    def _count(self, raw: dict | None) -> None:
        """Count a call's usage, and charge what it cost to `on_cost`."""
        tokens_in, tokens_out, _ = self.usage.add(raw)
        usd = cost(self.model, tokens_in, tokens_out)
        if usd and self.on_cost:
            self.on_cost(usd)

    def _post(self, payload: dict, *, timeout_s: float | None = None) -> dict:
        r = self.client.post(f"{self.base_url}/chat/completions", json=payload,
                             headers={"Authorization": f"Bearer {self.api_key}"},
                             **({"timeout": timeout_s} if timeout_s is not None else {}))
        r.raise_for_status()
        body = r.json()
        self._count(body.get("usage"))
        return body

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
            **({"reasoning_effort": self.effort} if self.effort else {}),
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

    def complete_json_streamed(self, system: str, text: str, images: list[Path] | None, schema: dict | None,
                               on_reasoning: Callable[[str], None]) -> dict:
        """`complete_json` over streamed chat completions, for hosts whose model sends its reasoning as
        `reasoning_content` deltas (Muse Spark Open on Baseten): `on_reasoning` hears each piece as it is written.
        Falls back to `complete_json` if the host refuses the stream or sends no JSON."""
        content = [{"type": "text", "text": text}] + [_image_part(p) for p in images or []]
        strict = bool(schema) and self.strict
        sys_text = system if strict or not schema else (
            system + "\n\nReply with one JSON object matching this schema:\n" + json.dumps(schema))
        payload = {
            "model": self.model, "stream": True, "temperature": 0.2,
            "messages": [{"role": "system", "content": sys_text}, {"role": "user", "content": content}],
            "response_format": ({"type": "json_schema", "json_schema": {"name": "reply", "schema": schema, "strict": True}}
                                if strict else {"type": "json_object"}),
            **({"reasoning_effort": self.effort} if self.effort else {}),
        }
        out = ""
        with self.client.stream("POST", f"{self.base_url}/chat/completions", json=payload,
                                headers={"Authorization": f"Bearer {self.api_key}"}) as r:
            if r.status_code in (400, 404, 422):  # no streaming (or no structured output) here
                r.read()
                return self.complete_json(system, text, images, schema)
            r.raise_for_status()
            for line in r.iter_lines():
                if not line.startswith("data: ") or line.strip() == "data: [DONE]":
                    continue
                for choice in json.loads(line[6:]).get("choices", []):
                    delta = choice.get("delta") or {}
                    thought = delta.get("reasoning_content") or delta.get("reasoning")
                    if thought:
                        on_reasoning(thought)
                    out += delta.get("content") or ""
        if not out.strip():
            return self.complete_json(system, text, images, schema)
        return json.loads(_strip_fence(out))

    def complete_json_reasoning(self, system: str, text: str, images: list[Path] | None, schema: dict | None,
                                on_reasoning: Callable[[str], None]) -> dict:
        """`complete_json`, streamed through the Responses endpoint so `on_reasoning` hears each reasoning summary as
        the model writes it. Falls back to `complete_json` (no summaries) when the host does not offer it."""
        if not self.streams_reasoning:
            return self.complete_json(system, text, images, schema)
        content = [{"type": "input_text", "text": text}] + [
            {"type": "input_image", "image_url": _image_part(p)["image_url"]["url"]} for p in images or []]
        fmt = ({"type": "json_schema", "name": "reply", "schema": schema, "strict": True} if schema
               else {"type": "json_object"})
        payload = {"model": self.model, "instructions": system, "stream": True, "temperature": 0.2,
                   "input": [{"role": "user", "content": content}], "text": {"format": fmt},
                   "reasoning": {"summary": "auto", **({"effort": self.effort} if self.effort else {})}}
        out = ""
        with self.client.stream("POST", f"{self.base_url}/responses", json=payload,
                                headers={"Authorization": f"Bearer {self.api_key}"}) as r:
            if r.status_code in (400, 404, 422):  # no Responses endpoint, or not with these options
                r.read()
                self.streams_reasoning = False
                return self.complete_json(system, text, images, schema)
            r.raise_for_status()
            for line in r.iter_lines():
                if not line.startswith("data:") or line[5:].strip() in ("", "[DONE]"):
                    continue
                try:
                    event = json.loads(line[5:])
                except json.JSONDecodeError:
                    continue
                kind = event.get("type", "")
                if kind == "response.reasoning_summary_text.done" and event.get("text"):
                    on_reasoning(event["text"].strip())
                elif kind == "response.output_text.delta":
                    out += event.get("delta", "")
                elif kind in ("response.completed", "response.incomplete", "response.failed"):
                    self._count((event.get("response") or {}).get("usage"))   # billed however it ended
                if kind in ("response.failed", "error"):
                    raise RuntimeError(f"{model_label(self.model)} failed: {json.dumps(event)[:300]}")
        return json.loads(_strip_fence(out))

    def chat(self, messages: list[dict], tools: list[dict], *, timeout_s: float | None = None) -> dict:
        """One assistant turn with tools: returns the message (content and/or tool_calls)."""
        payload = {
            "model": self.model, "messages": messages, "tools": tools, "temperature": 0.2,
            **({"reasoning_effort": self.effort} if self.effort else {}),
        }
        body = self._post(payload, timeout_s=timeout_s)
        return body["choices"][0]["message"]


def transcribe(wav: bytes, keywords: list[str] | None = None, client: httpx.Client | None = None) -> dict:
    """Speech to text with Muse Voice Transcribe: one push-to-talk clip (mono 16-bit PCM WAV, 16 or 24 kHz) in, its
    transcript out. `keywords` bias recognition toward jargon and names ("transom", "Clash7") without forcing them.

        META_VOICE_MODEL    muse-voice-transcribe-1.0
    """
    load_env()
    base = os.environ.get("META_API_BASE_URL", "https://api.meta.ai/v1").rstrip("/")
    settings = {"model": model_id("voice"), "audioEncoding": "WAV",
                "mode": "PUSH_TO_TALK", "languageBias": ["English"], **({"keywords": keywords} if keywords else {})}
    c = client or httpx.Client(timeout=_env_float("SIGHTLINE_VOICE_TIMEOUT_S", 60))
    r = c.post(f"{base}/asr/transcribe", headers={"Authorization": f"Bearer {os.environ['META_API_KEY']}",
                                                  "Accept": "application/json"},
               files={"request": (None, json.dumps(settings), "application/json"), "audio": ("clip.wav", wav, "audio/wav")})
    r.raise_for_status()
    body = r.json()
    return {"transcript": (body.get("transcript") or "").strip(), "duration_ms": body.get("audioDurationMs")}


def escalation_info() -> dict:
    """The model a second try runs on, and whether escalations are offered to this request (`settings.escalation`):
    {model, label, mode: off | button | auto, available}."""
    from . import settings
    load_env()
    model = model_id("escalation")
    return {"model": model, "label": model_label(model), "mode": settings.escalation(),
            "available": bool(os.environ.get("META_API_KEY"))}


def escalation_model(timeout_s: float | None = None) -> MetaChatModel:
    """The larger model for a second try at a clash (docs/escalation.md): Muse Wonder by default, effort medium
    unless the owner or the settings say otherwise (role "escalation"), every call charged to the day's limit."""
    from . import spend
    load_env()
    if timeout_s is None:
        timeout_s = _env_float("SIGHTLINE_ESCALATION_TIMEOUT_S", 240)
    model = MetaChatModel(model=escalation_info()["model"], timeout_s=timeout_s,
                          reasoning_effort=os.environ.get("META_ESCALATION_EFFORT", "medium"))
    model.role = "escalation"
    model.on_cost = spend.charge
    return model


def triage_model_info() -> dict:
    """Which model titles and triages for this request, without building a client: {model, open_weights, images,
    note?}. Muse Spark Open when its host key is set and the open-weights model is switched on (settings.open_weights:
    the owner's own choice, else the setting for everyone, else the default), else Muse Spark."""
    from . import settings
    load_env()
    key = os.environ.get("TRIAGE_API_KEY") or os.environ.get("BASETEN_API_KEY")
    if key and settings.open_weights():
        return {"model": os.environ.get("TRIAGE_MODEL", "meta-models/muse-spark-open"), "open_weights": True,
                "images": os.environ.get("TRIAGE_IMAGES", "1") != "0"}
    return {"model": model_id("proposal"), "open_weights": False, "images": True,
            "note": "The open-weights model is switched off; using Muse Spark." if key
            else "No open-weights host configured (TRIAGE_API_KEY); using Muse Spark."}


def triage_model(timeout_s: float | None = None) -> tuple[MetaChatModel, dict]:
    """The model for bulk triage and clash titles, and a description of it for the UI (`triage_model_info`)."""
    info = triage_model_info()
    if info["open_weights"]:
        model = MetaChatModel(os.environ.get("TRIAGE_API_BASE_URL", "https://inference.baseten.co/v1"),
                              os.environ.get("TRIAGE_API_KEY") or os.environ.get("BASETEN_API_KEY"), info["model"],
                              timeout_s, reasoning_effort=os.environ.get("TRIAGE_REASONING_EFFORT", ""))
    else:
        model = MetaChatModel(timeout_s=timeout_s)
    model.role = "triage"
    return model, info
