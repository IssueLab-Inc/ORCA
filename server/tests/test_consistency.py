"""The model-consistency readings and their comparison (consistency.py, docs/editing-parity.md)."""
import ifcopenshell.util.element
import pytest

from sightline import consistency, edits
from sightline.fixtures import build_parametric_fixture
from sightline.scene import IfcScene


@pytest.fixture
def scene(tmp_path):
    s = IfcScene([build_parametric_fixture(tmp_path / "param.ifc")])
    return s, {s.entity(g).Name: g for g in s.bounds()}


def test_a_consistent_model_reads_true_on_every_rule(scene):
    s, g = scene
    r = consistency.measure(s, list(g.values()))
    assert r[(g["W1"], "layers")].values == (0.0,) and r[(g["SL1"], "layers")].values == (0.0,)
    assert r[(g["BM1"], "profile")].values == (0.0,) * 4 and r[(g["BM1"], "axis")].values == (0.0, 0.0)
    assert r[(g["W1"], "axis")].values == (0.0, 0.0)
    (join,) = [v for k, v in r.items() if k[1] == "joins"]
    assert join.values == (0.0,)
    assert {k[1] for k in r if k[0] == g["F1"]} == {"type"} and (g["W2"], "quantities") in r


def test_only_what_an_edit_makes_worse_counts(scene):
    s, g = scene
    w1 = s.entity(g["W1"])
    usage = ifcopenshell.util.element.get_material(w1)
    usage.ForLayerSet.MaterialLayers[0].LayerThickness = 0.05   # the model already says two things: 285 vs 250 mm
    before = consistency.measure(s, [g["W1"]])
    assert before[(g["W1"], "layers")].values[0] == pytest.approx(0.035)
    with edits.trial_files(s, {0}):
        s.translate([g["W1"]], (0.0, 0.0, 0.5))     # a move changes nothing about its layers: not an issue
        assert consistency.compare(s, before, consistency.measure(s, [g["W1"]])) == []


def test_a_type_whose_map_changed_changes_every_element_of_it(scene):
    s, g = scene
    before = consistency.measure(s, [g["F1"]])
    with edits.trial_files(s, {0}):
        (item,) = [i for r in s.entity(g["F1"]).Representation.Representations for i in r.Items]
        item.MappingSource.MappedRepresentation.Items[0].Depth = 0.5
        (issue,) = consistency.compare(s, before, consistency.measure(s, [g["F1"]]))
        assert issue.rule == "type" and issue.severity == "block" and "FT-BOX" in issue.text
        assert consistency.compare(s, before, consistency.measure(s, [g["F1"]]), allow=frozenset({"type"})) == []


def test_a_set_other_elements_share_changed_in_place_changes_them_too(scene):
    s, g = scene
    before = consistency.measure(s, [g["W1"]])
    assert before[(g["W1"], "shared")].words["others"] == 1   # W2, through their type
    with edits.trial_files(s, {0}):
        ifcopenshell.util.element.get_material(s.entity(g["W1"])).ForLayerSet.MaterialLayers[2].LayerThickness = 0.05
        issues = consistency.compare(s, before, consistency.measure(s, [g["W1"]]))
        (shared,) = [i for i in issues if i.rule == "shared"]
        assert shared.severity == "block" and "shared by 1 other element" in shared.text


def test_quantities_warn_only_when_the_body_changed_and_they_did_not(scene):
    s, g = scene
    before = consistency.measure(s, [g["SL1"]])
    with edits.trial_files(s, {0}):
        edits.stretch(s, g["SL1"], "side", 0.1, normal=(1.0, 0.0, 0.0))   # 100 mm wider: its depth stays
        (issue,) = consistency.compare(s, before, consistency.measure(s, [g["SL1"]]))
        assert issue.rule == "quantities" and issue.severity == "warn" and "Qto_SlabBaseQuantities" in issue.text
    with edits.trial_files(s, {0}):
        s.translate([g["SL1"]], (0.0, 0.0, 1.0))
        assert consistency.compare(s, before, consistency.measure(s, [g["SL1"]])) == []


def test_a_path_join_is_measured_in_plan(scene):
    s, g = scene
    before = consistency.measure(s, [g["W1"]])
    with edits.trial_files(s, {0}):
        s.translate([g["W1"]], (0.0, 0.0, 0.4))
        assert consistency.compare(s, before, consistency.measure(s, [g["W1"]])) == []
    with edits.trial_files(s, {0}):
        s.translate([g["W2"]], (0.3, 0.0, 0.0))
        (issue,) = consistency.compare(s, before, consistency.measure(s, [g["W1"]]))
        assert issue.rule == "joins" and "300 mm apart" in issue.text
