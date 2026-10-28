import pytest

from sightline import settings


@pytest.fixture(autouse=True)
def settings_store(tmp_path, monkeypatch):
    """Each test gets its own store for the settings for everyone (settings.py), never the developer's file."""
    monkeypatch.setenv("SIGHTLINE_SETTINGS_FILE", str(tmp_path / "settings.json"))
    monkeypatch.delenv("MODAL_TASK_ID", raising=False)
    settings.reset_cache()
    yield tmp_path / "settings.json"
    settings.reset_cache()
