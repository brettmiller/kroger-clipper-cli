from pathlib import Path

import pytest

from kroger_clipper import paths


@pytest.fixture(autouse=True)
def _clear_xdg(monkeypatch):
    monkeypatch.delenv("XDG_STATE_HOME", raising=False)


def test_state_dir_defaults_to_local_state(monkeypatch, tmp_path):
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    assert paths.state_dir() == tmp_path / ".local" / "state" / "kroger-clipper"


def test_xdg_env_vars_win(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "st"))
    assert paths.state_dir() == tmp_path / "st" / "kroger-clipper"


def test_session_file_lives_outside_any_repo(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "st"))
    assert paths.session_file() == tmp_path / "st" / "kroger-clipper" / "session.json"
