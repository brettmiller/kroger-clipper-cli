import json

import pytest
from click.testing import CliRunner

from kroger_clipper import cli, coupons, errors, transport


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def no_network(monkeypatch):
    """Nothing in these tests may touch Kroger."""
    monkeypatch.setattr(transport, "build", lambda banner: object())


def fake_coupons(count=2):
    return [
        {
            "id": f"c{i}",
            "brandName": "Acme",
            "shortDescription": f"$1 off {i}",
            "expirationDate": "2026-10-01",
        }
        for i in range(count)
    ]


def summary(**overrides):
    base = {
        "clipped": 2,
        "already_clipped": 0,
        "failures": [],
        "attempted": 2,
        "stopped": None,
        "card_full": False,
    }
    return {**base, **overrides}


def test_dry_run_lists_and_clips_nothing(runner, no_network, monkeypatch):
    monkeypatch.setattr(coupons, "list_unclipped", lambda *_: fake_coupons(2))
    monkeypatch.setattr(coupons, "clip_all", lambda *a, **k: pytest.fail("dry run must not clip"))

    result = runner.invoke(cli.main, ["clip", "--dry-run"])

    assert result.exit_code == 0
    assert "2 unclipped coupon(s)" in result.output
    assert "Acme: $1 off 0" in result.output


def test_dry_run_json_is_parseable(runner, no_network, monkeypatch):
    monkeypatch.setattr(coupons, "list_unclipped", lambda *_: fake_coupons(1))

    result = runner.invoke(cli.main, ["clip", "--dry-run", "--json"])

    payload = json.loads(result.output)
    assert payload[0]["id"] == "c0"
    assert payload[0]["brand"] == "Acme"


def test_missing_session_exits_2(runner, monkeypatch):
    def boom(_banner):
        raise errors.SessionMissing("no session at /nowhere")

    monkeypatch.setattr(transport, "build", boom)
    result = runner.invoke(cli.main, ["clip"])

    assert result.exit_code == cli.EXIT_SESSION_EXPIRED
    assert "kroger-clipper login" in result.output


def test_expired_session_exits_2_not_3(runner, no_network, monkeypatch):
    """The whole point of exit 2: a dead session is a re-login, not a broken API."""

    def boom(*_a, **_k):
        raise errors.SessionExpired("Kroger rejected the session")

    monkeypatch.setattr(coupons, "list_unclipped", lambda *_: fake_coupons(1))
    monkeypatch.setattr(coupons, "clip_all", boom)

    result = runner.invoke(cli.main, ["clip"])

    assert result.exit_code == cli.EXIT_SESSION_EXPIRED
    assert "kroger-clipper login" in result.output


def test_blocked_exits_4(runner, no_network, monkeypatch):
    def boom(*_a, **_k):
        raise errors.Blocked("rate limited (HTTP 429)")

    monkeypatch.setattr(coupons, "list_unclipped", boom)
    result = runner.invoke(cli.main, ["clip"])

    assert result.exit_code == cli.EXIT_BLOCKED


def test_structural_error_exits_3(runner, no_network, monkeypatch):
    def boom(*_a, **_k):
        raise errors.StructuralError("response is missing data.coupons")

    monkeypatch.setattr(coupons, "list_unclipped", boom)
    result = runner.invoke(cli.main, ["clip"])

    assert result.exit_code == cli.EXIT_STRUCTURAL


def test_a_full_card_exits_0(runner, no_network, monkeypatch):
    monkeypatch.setattr(coupons, "list_unclipped", lambda *_: fake_coupons(5))
    monkeypatch.setattr(
        coupons, "clip_all", lambda *a, **k: summary(clipped=0, attempted=1, card_full=True)
    )

    result = runner.invoke(cli.main, ["clip"])

    assert result.exit_code == 0
    assert "Card is full" in result.output


def test_consecutive_failures_exit_3(runner, no_network, monkeypatch):
    monkeypatch.setattr(coupons, "list_unclipped", lambda *_: fake_coupons(9))
    monkeypatch.setattr(
        coupons,
        "clip_all",
        lambda *a, **k: summary(clipped=0, attempted=5, stopped="5 consecutive failures"),
    )

    result = runner.invoke(cli.main, ["clip"])

    assert result.exit_code == cli.EXIT_STRUCTURAL
    assert "Stopped early" in result.output


def test_already_clipped_is_reported(runner, no_network, monkeypatch):
    monkeypatch.setattr(coupons, "list_unclipped", lambda *_: fake_coupons(3))
    monkeypatch.setattr(coupons, "clip_all", lambda *a, **k: summary(already_clipped=2))

    result = runner.invoke(cli.main, ["clip"])

    assert result.exit_code == 0
    assert "2 were already on the card" in result.output


def test_nonsense_delay_exits_3(runner, no_network, monkeypatch):
    monkeypatch.setattr(coupons, "list_unclipped", lambda *_: fake_coupons(1))
    result = runner.invoke(cli.main, ["clip", "--delay", "5", "1"])

    assert result.exit_code == cli.EXIT_STRUCTURAL


def test_max_clips_is_passed_through(runner, no_network, monkeypatch):
    seen = {}

    def capture(*_a, **kwargs):
        seen.update(kwargs)
        return summary()

    monkeypatch.setattr(coupons, "list_unclipped", lambda *_: fake_coupons(10))
    monkeypatch.setattr(coupons, "clip_all", capture)
    runner.invoke(cli.main, ["clip", "--max-clips", "3"])

    assert seen["limit"] == 3
