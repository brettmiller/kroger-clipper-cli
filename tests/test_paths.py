from pathlib import Path

import pytest

from kroger_clipper import paths


@pytest.fixture(autouse=True)
def _clear_xdg(monkeypatch):
    for var in ("XDG_CONFIG_HOME", "XDG_STATE_HOME"):
        monkeypatch.delenv(var, raising=False)


def test_config_dir_defaults_to_dot_config(monkeypatch, tmp_path):
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    assert paths.config_dir() == tmp_path / ".config" / "kroger-clipper"


def test_state_dir_defaults_to_local_state(monkeypatch, tmp_path):
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    assert paths.state_dir() == tmp_path / ".local" / "state" / "kroger-clipper"


def test_xdg_env_vars_win(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "st"))
    assert paths.config_dir() == tmp_path / "cfg" / "kroger-clipper"
    assert paths.state_dir() == tmp_path / "st" / "kroger-clipper"


def test_session_file_lives_outside_any_repo(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "st"))
    assert paths.session_file() == tmp_path / "st" / "kroger-clipper" / "session.json"
