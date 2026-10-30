from pathlib import Path

import pytest

from sightline.agent import Clash, resolve
from sightline.fixtures import build_clash_fixture
from sightline.scene import IfcScene


class ScriptedModel:
    """Stands in for Muse Spark: first round proposes a drop that hits the pipe, second round a deeper one."""

    def __init__(self):
        self.calls = []

    def complete_json(self, system, text, images=None):
        self.calls.append(text)
        if len(self.calls) == 1:
            return {"understanding": "The duct passes through the beam web.",
                    "candidates": [{"title": "Drop duct 400 mm", "move": "A", "delta_m": [0, 0, -0.40],
                                    "rationale": "Below the beam", "also_needs": "none"}]}
        return {"candidates": [{"title": "Drop duct 800 mm", "move": "A", "delta_m": [0, 0, -0.80],
                                "rationale": "Below beam and pipe", "also_needs": "2 x 45° offsets"},
                               {"title": "Shift duct 3.5 m east", "move": "A", "delta_m": [3.5, 0, 0],
                                "rationale": "Past the end of the beam", "also_needs": "longer run"}]}


def test_failed_attempt_is_fed_back_and_only_verified_options_survive(tmp_path: Path):
    path = build_clash_fixture(tmp_path / "f.ifc")
    s = IfcScene(path)
    duct, beam = s.model.by_type("IfcDuctSegment")[0].GlobalId, s.model.by_type("IfcBeam")[0].GlobalId
    model = ScriptedModel()

    result = resolve(path, Clash(duct, beam, distance_m=-0.3), model, max_rounds=3, want=2)

    assert result.understanding.startswith("The duct")
    assert [a.passed for a in result.attempts] == [False, True, True]
    assert "IfcPipeSegment" in result.attempts[0].reason
    assert "Drop duct 400 mm" in model.calls[1]           # the failure was reported back to the model
    assert [o.title for o in result.options] == ["Drop duct 800 mm", "Shift duct 3.5 m east"]
    # placements are flattened row-major 4x4 world matrices; index 11 is Z
    assert result.options[0].placements[duct][11] == pytest.approx(1.85)


def test_attempts_leave_the_loaded_model_unchanged(tmp_path: Path):
    s = IfcScene(build_clash_fixture(tmp_path / "f.ifc"))
    duct, beam = s.model.by_type("IfcDuctSegment")[0].GlobalId, s.model.by_type("IfcBeam")[0].GlobalId
    resolve(s, Clash(duct, beam), ScriptedModel(), max_rounds=2)
    assert s.placement(duct)[2, 3] == pytest.approx(2.65)


def test_env_file_fills_missing_settings_only(tmp_path, monkeypatch):
    from sightline.meta_client import load_env
    env = tmp_path / ".env"
    env.write_text("# comment\nMETA_MODEL=from-file\nMETA_API_KEY=file-key\n")
    monkeypatch.setenv("META_API_KEY", "shell-key")
    monkeypatch.delenv("META_MODEL", raising=False)
    load_env(env)
    import os
    assert os.environ["META_MODEL"] == "from-file"
    assert os.environ["META_API_KEY"] == "shell-key"


def test_ranking_prefers_comfortable_clearance_and_drops_repeats():
    from sightline.agent import Option, _keep, _reason
    from sightline.verify import Hit

    def opt(title, dz, clear):
        return Option(title, ["d"], [0, 0, dz], "", "", clear, {}, "offset", [1.0, 2.0])

    kept: list = []
    for o in (opt("tight", 0.225, 0.025), opt("roomy", 0.25, 0.05), opt("roomy again", 0.252, 0.04)):
        _keep(kept, o)
    assert [o.title for o in kept] == ["tight", "roomy"]
    hits = [Hit("x", "IfcDuctSegment", "collision", -0.249), Hit("y", "IfcDuctSegment", "collision", -0.1),
            Hit("z", "IfcWall", "clearance", 0.01)]
    assert _reason(hits) == "collision with IfcDuctSegment x2 (worst -249 mm), clearance with IfcWall (+10 mm)"


def test_trials_show_each_candidate_before_its_check_and_attempts_name_what_they_hit(tmp_path: Path):
    path = build_clash_fixture(tmp_path / "f.ifc")
    s = IfcScene(path)
    duct, beam = s.model.by_type("IfcDuctSegment")[0].GlobalId, s.model.by_type("IfcBeam")[0].GlobalId
    pipe = s.model.by_type("IfcPipeSegment")[0].GlobalId
    events = []

    result = resolve(s, Clash(duct, beam), ScriptedModel(), max_rounds=2, on_event=events.append, trials=True)

    kinds = [e["type"] for e in events if e["type"] in ("checking", "trial", "attempt")]
    assert kinds == ["checking", "trial", "attempt"] * 3
    first = next(e for e in events if e["type"] == "trial")
    assert first == {"type": "trial", "index": 0, "kind": "move", "moved": [duct], "delta_m": [0, 0, -0.40], "pieces": None}
    assert result.attempts[0].hit_ids == [pipe] and result.attempts[1].hit_ids == []
    # without `trials` (plans run many agents at once) nothing is meshed or sent
    quiet = []
    resolve(s, Clash(duct, beam), ScriptedModel(), max_rounds=1, on_event=quiet.append)
    assert not [e for e in quiet if e["type"] == "trial"]


class ThinkingModel(ScriptedModel):
    """A model that streams reasoning summaries, like Muse Spark through Meta's Responses endpoint."""
    streams_reasoning = True

    def complete_json_reasoning(self, system, text, images, schema, on_reasoning):
        on_reasoning("Reading the duct and beam sizes.")
        on_reasoning("Checking room below the beam.")
        return self.complete_json(system, text, images)


def test_reasoning_summaries_stream_before_the_ideas_only_when_watched(tmp_path: Path):
    s = IfcScene(build_clash_fixture(tmp_path / "f.ifc"))
    duct, beam = s.model.by_type("IfcDuctSegment")[0].GlobalId, s.model.by_type("IfcBeam")[0].GlobalId
    events = []
    resolve(s, Clash(duct, beam), ThinkingModel(), max_rounds=1, on_event=events.append, trials=True)
    kinds = [e["type"] for e in events]
    assert kinds[:4] == ["thinking", "reasoning", "reasoning", "ideas"]
    assert events[1] == {"type": "reasoning", "round": 1, "text": "Reading the duct and beam sizes."}
    ideas, checking = events[3], [e for e in events if e["type"] == "checking"]
    assert ideas["count"] == len(ideas["candidates"]) == len(checking)
    assert ideas["candidates"] == [{"title": e["title"], "kind": e["kind"]} for e in checking]
    tried = [e for e in events if e["type"] == "attempt"]
    assert tried and all(isinstance(e["seconds"], float) and e["seconds"] >= 0 for e in tried)   # each check, timed
    assert all(e["checked"] > 0 for e in tried if e["passed"])
    quiet = []  # plans run several agents at once and show no thinking
    resolve(s, Clash(duct, beam), ThinkingModel(), max_rounds=1, on_event=quiet.append)
    assert "reasoning" not in [e["type"] for e in quiet]
