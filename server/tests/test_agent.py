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
