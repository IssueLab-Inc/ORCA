import json

import pytest
from fastapi.testclient import TestClient

from sightline import app as app_module
from sightline import meta_client, owner, settings
from sightline.meta_client import MetaChatModel

TOKEN = "t" * 40


def test_the_store_keeps_settings_across_a_restart(settings_store):
    settings.update({"open_weights": True, "effort": "medium"})
    assert json.loads(settings_store.read_text())["effort"] == "medium"
    settings.reset_cache()  # a new process reads the file again
    assert settings.current() == settings.Settings(open_weights=True, effort="medium", triage_effort=None)
    settings.update({"effort": None})  # back to the environment's default
    settings.reset_cache()
    assert settings.current().effort is None and settings.current().open_weights is True


def test_unknown_values_are_refused():
    for bad in ({"effort": "extreme"}, {"open_weights": "yes"}, {"caps": False}):
        with pytest.raises(ValueError):
            settings.update(bad)


def test_a_broken_store_falls_back_to_the_defaults(settings_store):
    settings_store.write_text("not json")
    assert settings.current() == settings.Settings()


def test_effort_is_the_owners_then_everyones_then_the_environments():
    model = MetaChatModel("https://example/v1", "k", "m", reasoning_effort="low")
    assert model.effort == "low"
    settings.update({"effort": "medium", "triage_effort": "high"})
    assert model.effort == "medium"  # a visitor gets the setting for everyone
    tokens = owner.enter(True, json.dumps({"effort": "minimal"}))
    try:
        assert model.effort == "minimal"  # the owner's own wins for the owner
        model.role = "triage"
        assert model.effort == "high"  # the owner set no triage effort: everyone's
    finally:
        owner.leave(tokens)


def test_open_weights_is_off_unless_switched_on(monkeypatch):
    monkeypatch.delenv("SIGHTLINE_OPEN_WEIGHTS", raising=False)
    assert settings.open_weights() is False
    settings.update({"open_weights": True})
    assert settings.open_weights() is True
    tokens = owner.enter(True, json.dumps({"open_weights": False}))
    try:
        assert settings.open_weights() is False  # the owner's own choice, for the owner's requests
        seen = []
        owner.spawn(lambda: seen.append(settings.open_weights())).join()  # and in a stream's worker
        assert seen == [False]
    finally:
        owner.leave(tokens)
    tokens = owner.enter(False, json.dumps({"open_weights": False}))  # a visitor asking is not enough
    try:
        assert settings.open_weights() is True
    finally:
        owner.leave(tokens)


def test_triage_model_uses_the_host_only_when_switched_on(monkeypatch):
    monkeypatch.setattr(meta_client, "load_env", lambda: None)
    monkeypatch.setenv("META_API_KEY", "m")
    monkeypatch.setenv("BASETEN_API_KEY", "b")
    monkeypatch.delenv("TRIAGE_API_KEY", raising=False)
    monkeypatch.delenv("SIGHTLINE_OPEN_WEIGHTS", raising=False)
    model, info = meta_client.triage_model()
    assert not info["open_weights"] and model.base_url == "https://api.meta.ai/v1" and "switched off" in info["note"]
    settings.update({"open_weights": True})
    model, info = meta_client.triage_model()
    assert info["open_weights"] and model.base_url == "https://inference.baseten.co/v1"


def test_only_the_owner_reads_and_changes_the_settings_for_everyone(monkeypatch):
    monkeypatch.setenv("SIGHTLINE_OWNER_TOKEN", TOKEN)
    monkeypatch.setenv("BASETEN_API_KEY", "b")
    c = TestClient(app_module.app, base_url="https://testserver")
    assert c.get("/api/settings").status_code == 403
    assert c.put("/api/settings", json={"open_weights": True}).status_code == 403
    assert settings.current().open_weights is None
    c.post("/api/owner/unlock", json={"token": TOKEN})
    r = c.put("/api/settings", json={"open_weights": True, "triage_effort": "low"})
    assert r.status_code == 200
    body = r.json()
    assert body["everyone"] == {"open_weights": True, "effort": None, "triage_effort": "low", "escalation": None,
                                "escalation_effort": None} and body["host"] is True
    assert c.put("/api/settings", json={"effort": "extreme"}).status_code == 400
    assert c.get("/api/settings").json()["everyone"]["open_weights"] is True


def test_models_says_which_model_this_request_would_use(monkeypatch):
    monkeypatch.setattr(meta_client, "load_env", lambda: None)
    monkeypatch.setenv("BASETEN_API_KEY", "b")
    monkeypatch.delenv("SIGHTLINE_OPEN_WEIGHTS", raising=False)
    monkeypatch.setenv("SIGHTLINE_OWNER_TOKEN", TOKEN)
    c = TestClient(app_module.app, base_url="https://testserver")
    assert c.get("/api/models").json()["triage"]["open_weights"] is False
    settings.update({"open_weights": True})
    assert c.get("/api/models").json()["triage"] == {"model": "meta-models/muse-spark-open", "open_weights": True, "images": True}
    c.post("/api/owner/unlock", json={"token": TOKEN})  # the owner's own choice wins for the owner
    assert c.get("/api/models", headers={"X-Sightline-Settings": '{"open_weights": false}'}).json()["triage"]["open_weights"] is False
