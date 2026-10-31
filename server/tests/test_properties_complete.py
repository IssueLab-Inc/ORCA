"""Every property value Northbank gives an object is shown, and the hidden note never is (evals/properties_complete.py).
Skipped when the demo models are not cloned ($DEMO_MODELS, ../demo-models) or copied into samples/."""
import importlib.util
from pathlib import Path

import pytest

EVAL = Path(__file__).resolve().parents[2] / "evals" / "properties_complete.py"
spec = importlib.util.spec_from_file_location("properties_complete", EVAL)
complete = importlib.util.module_from_spec(spec)
spec.loader.exec_module(complete)


@pytest.mark.skipif(not complete.northbank(), reason="Northbank is not here (DEMO_MODELS, ../demo-models or samples/)")
def test_the_panel_shows_every_value_northbank_gives():
    rows, wrong = complete.check(complete.northbank())
    assert not wrong, "\n".join(wrong[:20])
    assert sum(r["values"] for r in rows) > 5000
