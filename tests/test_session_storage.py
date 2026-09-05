import json
import stat

import pytest

from kroger_clipper import session

STATE = {"cookies": [{"name": "kroger-si-customer-data-token", "value": "secret"}]}
HEADERS = {"x-facility-id": "09900999", "x-modality-type": "IN_STORE"}


def test_session_written_with_owner_only_permissions(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    session._write_session(STATE, HEADERS)

    path = tmp_path / "kroger-clipper" / "session.json"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600

    saved = json.loads(path.read_text())
    assert saved["storage_state"] == STATE
    assert saved["context_headers"] == HEADERS


def test_pre_existing_loose_permissions_are_tightened(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    path = tmp_path / "kroger-clipper" / "session.json"
    path.parent.mkdir(parents=True)
    path.write_text("{}")
    path.chmod(0o644)

    session._write_session(STATE)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_headers_default_to_empty_rather_than_null(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    session._write_session(STATE)

    saved = json.loads((tmp_path / "kroger-clipper" / "session.json").read_text())
    assert saved["context_headers"] == {}


def test_load_session_round_trips(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    session._write_session(STATE, HEADERS)

    loaded = session.load_session()
    assert loaded["storage_state"] == STATE
    assert loaded["context_headers"] == HEADERS


def test_load_session_raises_when_absent(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    with pytest.raises(session.SessionMissing):
        session.load_session()


def test_scope_state_keeps_only_banner_cookies():
    state = {
        "cookies": [
            {"name": "loggedIn", "domain": "www.kroger.com"},
            {"name": "x-ms-cpim-sso", "domain": ".login.kroger.com"},
            {"name": "NID", "domain": ".google.com"},
            {"name": "SEARCH_SAMESITE", "domain": "google.com"},
        ],
        "origins": [],
    }
    kept = {c["name"] for c in session._scope_state(state, "kroger.com")["cookies"]}
    assert kept == {"loggedIn", "x-ms-cpim-sso"}


def test_scope_state_preserves_other_keys():
    state = {"cookies": [], "origins": [{"origin": "https://www.kroger.com"}]}
    assert session._scope_state(state, "kroger.com")["origins"] == state["origins"]
