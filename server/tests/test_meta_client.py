import json

import httpx

from sightline.meta_client import MetaChatModel


def _sse(events):
    return "".join(f"event: {e['type']}\ndata: {json.dumps(e)}\n\n" for e in events) + "data: [DONE]\n\n"


def test_responses_stream_gives_reasoning_summaries_then_the_json():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"], seen["body"] = request.url.path, json.loads(request.content)
        return httpx.Response(200, text=_sse([
            {"type": "response.created"},
            {"type": "response.reasoning_summary_text.delta", "delta": "Weighing"},
            {"type": "response.reasoning_summary_text.done", "text": "Weighing the opening against the duct size."},
            {"type": "response.reasoning_summary_text.done", "text": " Choosing a local offset. "},
            {"type": "response.output_text.delta", "delta": '{"candidates": '},
            {"type": "response.output_text.delta", "delta": "[]}"},
            {"type": "response.completed"},
        ]), headers={"content-type": "text/event-stream"})

    m = MetaChatModel("https://api.meta.ai/v1", "k", "muse", reasoning_effort="low")
    m.client = httpx.Client(transport=httpx.MockTransport(handler))
    notes = []
    assert m.complete_json_reasoning("sys", "text", None, None, notes.append) == {"candidates": []}
    assert notes == ["Weighing the opening against the duct size.", "Choosing a local offset."]
    assert seen["path"] == "/v1/responses"
    assert seen["body"]["reasoning"] == {"summary": "auto", "effort": "low"} and seen["body"]["instructions"] == "sys"


def test_without_a_responses_endpoint_it_falls_back_to_chat_completions():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/responses"):
            return httpx.Response(404, json={"error": "not here"})
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"ok": true}'}}]})

    m = MetaChatModel("https://api.meta.ai/v1", "k", "muse")
    m.client = httpx.Client(transport=httpx.MockTransport(handler))
    assert m.complete_json_reasoning("sys", "text", None, None, lambda note: None) == {"ok": True}
    assert m.streams_reasoning is False  # not tried again


def test_other_hosts_do_not_try_the_responses_endpoint():
    assert MetaChatModel("https://inference.baseten.co/v1", "k", "m").streams_reasoning is False
