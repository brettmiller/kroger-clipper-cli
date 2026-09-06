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
            "categories": ["Dairy"] if i % 2 == 0 else ["Frozen"],
            "modalities": ["IN_STORE"],
        }
        for i in range(count)
    ]


def summary(**overrides):
    base = {
        "succeeded": 2,
        "already_done": 0,
        "failures": [],
        "attempted": 2,
        "stopped": None,
        "card_full": False,
    }
    return {**base, **overrides}


def test_dry_run_lists_and_clips_nothing(runner, no_network, monkeypatch):
    monkeypatch.setattr(coupons, "list_by_status", lambda *_: fake_coupons(2))
    monkeypatch.setattr(coupons, "apply_all", lambda *a, **k: pytest.fail("dry run must not clip"))

    result = runner.invoke(cli.main, ["clip", "--dry-run"])

    assert result.exit_code == 0
    assert "2 unclipped coupon(s)" in result.output
    assert "Acme: $1 off 0" in result.output


def test_dry_run_json_is_parseable(runner, no_network, monkeypatch):
    monkeypatch.setattr(coupons, "list_by_status", lambda *_: fake_coupons(1))

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

    monkeypatch.setattr(coupons, "list_by_status", lambda *_: fake_coupons(1))
    monkeypatch.setattr(coupons, "apply_all", boom)

    result = runner.invoke(cli.main, ["clip"])

    assert result.exit_code == cli.EXIT_SESSION_EXPIRED
    assert "kroger-clipper login" in result.output


def test_blocked_exits_4(runner, no_network, monkeypatch):
    def boom(*_a, **_k):
        raise errors.Blocked("rate limited (HTTP 429)")

    monkeypatch.setattr(coupons, "list_by_status", boom)
    result = runner.invoke(cli.main, ["clip"])

    assert result.exit_code == cli.EXIT_BLOCKED


def test_structural_error_exits_3(runner, no_network, monkeypatch):
    def boom(*_a, **_k):
        raise errors.StructuralError("response is missing data.coupons")

    monkeypatch.setattr(coupons, "list_by_status", boom)
    result = runner.invoke(cli.main, ["clip"])

    assert result.exit_code == cli.EXIT_STRUCTURAL


def test_a_full_card_exits_0(runner, no_network, monkeypatch):
    monkeypatch.setattr(coupons, "list_by_status", lambda *_: fake_coupons(5))
    monkeypatch.setattr(
        coupons, "apply_all", lambda *a, **k: summary(succeeded=0, attempted=1, card_full=True)
    )

    result = runner.invoke(cli.main, ["clip"])

    assert result.exit_code == 0
    assert "Card is full" in result.output


def test_consecutive_failures_exit_3(runner, no_network, monkeypatch):
    monkeypatch.setattr(coupons, "list_by_status", lambda *_: fake_coupons(9))
    monkeypatch.setattr(
        coupons,
        "apply_all",
        lambda *a, **k: summary(succeeded=0, attempted=5, stopped="5 consecutive failures"),
    )

    result = runner.invoke(cli.main, ["clip"])

    assert result.exit_code == cli.EXIT_STRUCTURAL
    assert "Stopped early" in result.output


def test_already_clipped_is_reported(runner, no_network, monkeypatch):
    monkeypatch.setattr(coupons, "list_by_status", lambda *_: fake_coupons(3))
    monkeypatch.setattr(coupons, "apply_all", lambda *a, **k: summary(already_done=2))

    result = runner.invoke(cli.main, ["clip"])

    assert result.exit_code == 0
    assert "2 were already on the card" in result.output


def test_nonsense_delay_exits_3(runner, no_network, monkeypatch):
    monkeypatch.setattr(coupons, "list_by_status", lambda *_: fake_coupons(1))
    result = runner.invoke(cli.main, ["clip", "--delay", "5", "1"])

    assert result.exit_code == cli.EXIT_STRUCTURAL


def test_max_clips_is_passed_through(runner, no_network, monkeypatch):
    seen = {}

    def capture(*_a, **kwargs):
        seen.update(kwargs)
        return summary()

    monkeypatch.setattr(coupons, "list_by_status", lambda *_: fake_coupons(10))
    monkeypatch.setattr(coupons, "apply_all", capture)
    runner.invoke(cli.main, ["clip", "--max-clips", "3"])

    assert seen["limit"] == 3


def test_top_level_help_shows_subcommand_options(runner):
    """Finding --dry-run should not require a second command."""
    out = runner.invoke(cli.main, ["--help"], prog_name="kroger-clipper").output

    assert "--dry-run" in out
    assert "--max-clips" in out
    assert "--delay" in out
    assert "kroger-clipper clip" in out
    assert "kroger-clipper login" in out


def test_bare_invocation_shows_the_same_help(runner):
    bare = runner.invoke(cli.main, [], prog_name="kroger-clipper").output
    explicit = runner.invoke(cli.main, ["--help"], prog_name="kroger-clipper").output
    assert bare == explicit


def test_hidden_commands_stay_hidden(runner):
    """capture is a maintenance tool, not part of the advertised interface.

    Matched on the section heading, not the bare word: login's own summary
    contains "capture the session".
    """
    out = runner.invoke(cli.main, ["--help"], prog_name="kroger-clipper").output

    assert "kroger-clipper capture" not in out
    assert "Record a real response" not in out


def test_help_is_not_repeated_for_every_subcommand(runner):
    """--help belongs in the top Options block once, not in each expansion."""
    out = runner.invoke(cli.main, ["--help"], prog_name="kroger-clipper").output
    assert out.count("Show this message and exit.") == 1


def test_subcommand_help_still_works_on_its_own(runner):
    out = runner.invoke(cli.main, ["clip", "--help"]).output
    assert "--dry-run" in out
    assert "Show this message and exit." in out


@pytest.fixture
def interactive(monkeypatch):
    monkeypatch.setattr(cli, "_interactive", lambda: True)


@pytest.fixture
def headless(monkeypatch):
    monkeypatch.setattr(cli, "_interactive", lambda: False)


def _fails_with(monkeypatch, exc, then=None):
    """transport.build raises once, then optionally succeeds."""
    calls = {"n": 0}

    def build(_banner):
        calls["n"] += 1
        if calls["n"] == 1 or then is None:
            raise exc
        return object()

    monkeypatch.setattr(transport, "build", build)
    monkeypatch.setattr(coupons, "list_by_status", lambda *_: then or [])
    return calls


def test_stale_session_prompts_and_retries_after_login(runner, interactive, monkeypatch):
    logins = []
    monkeypatch.setattr(cli.session_mod, "login", lambda b: logins.append(b))
    monkeypatch.setattr(coupons, "apply_all", lambda *a, **k: summary())
    _fails_with(monkeypatch, errors.SessionExpired("session rejected"), then=fake_coupons(1))

    result = runner.invoke(cli.main, ["clip"], input="y\n")

    assert logins == ["kroger.com"]
    assert result.exit_code == 0


def test_declining_the_prompt_exits_without_logging_in(runner, interactive, monkeypatch):
    monkeypatch.setattr(
        cli.session_mod, "login", lambda b: pytest.fail("must not sign in after a refusal")
    )
    _fails_with(monkeypatch, errors.SessionExpired("session rejected"))

    result = runner.invoke(cli.main, ["clip"], input="n\n")

    assert result.exit_code == cli.EXIT_SESSION_EXPIRED


def test_non_interactive_never_opens_a_browser(runner, headless, monkeypatch):
    """A cron run has nobody to sign in; prompting or launching Chrome is wrong."""
    monkeypatch.setattr(
        cli.session_mod, "login", lambda b: pytest.fail("must not sign in unattended")
    )
    _fails_with(monkeypatch, errors.SessionExpired("session rejected"))

    result = runner.invoke(cli.main, ["clip"])

    assert result.exit_code == cli.EXIT_SESSION_EXPIRED
    assert "Run `kroger-clipper login`" in result.output


def test_a_reset_connection_also_offers_login(runner, interactive, monkeypatch):
    logins = []
    monkeypatch.setattr(cli.session_mod, "login", lambda b: logins.append(b))
    monkeypatch.setattr(coupons, "apply_all", lambda *a, **k: summary())
    _fails_with(monkeypatch, errors.ConnectionReset("edge reset"), then=fake_coupons(1))

    result = runner.invoke(cli.main, ["clip"], input="y\n")

    assert logins == ["kroger.com"]
    assert result.exit_code == 0


def test_a_rate_limit_never_offers_login(runner, interactive, monkeypatch):
    """Signing in does not fix a 429, and retrying into one makes it worse."""
    monkeypatch.setattr(
        cli.session_mod, "login", lambda b: pytest.fail("must not sign in on a rate limit")
    )
    _fails_with(monkeypatch, errors.Blocked("rate limited (HTTP 429)"))

    result = runner.invoke(cli.main, ["clip"])

    assert result.exit_code == cli.EXIT_BLOCKED
    assert "Wait before retrying" in result.output


def test_it_retries_only_once(runner, interactive, monkeypatch):
    logins = []
    monkeypatch.setattr(cli.session_mod, "login", lambda b: logins.append(b))
    _fails_with(monkeypatch, errors.SessionExpired("session rejected"))

    result = runner.invoke(cli.main, ["clip"], input="y\n")

    assert logins == ["kroger.com"]
    assert "Still refused after signing in" in result.output
    assert result.exit_code == cli.EXIT_SESSION_EXPIRED


def test_a_failed_login_does_not_loop(runner, interactive, monkeypatch):
    def boom(_banner):
        raise errors.ChromeNotFound("no Google Chrome found")

    monkeypatch.setattr(cli.session_mod, "login", boom)
    _fails_with(monkeypatch, errors.SessionExpired("session rejected"))

    result = runner.invoke(cli.main, ["clip"], input="y\n")

    assert "Sign-in failed" in result.output
    assert result.exit_code == cli.EXIT_SESSION_EXPIRED


def test_version_resolves_against_the_real_distribution(runner):
    """The dist is kroger-clipper-cli; the import package is kroger_clipper."""
    result = runner.invoke(cli.main, ["--version"])

    assert result.exit_code == 0
    assert "version" in result.output


def test_department_filter_narrows_the_dry_run(runner, no_network, monkeypatch):
    monkeypatch.setattr(coupons, "list_by_status", lambda *_: fake_coupons(4))

    result = runner.invoke(cli.main, ["clip", "--dry-run", "--department", "Dairy"])

    assert result.exit_code == 0
    assert "2 unclipped coupon(s)" in result.output


def test_excluded_department_is_dropped(runner, no_network, monkeypatch):
    monkeypatch.setattr(coupons, "list_by_status", lambda *_: fake_coupons(4))

    result = runner.invoke(cli.main, ["clip", "--dry-run", "--exclude-department", "Frozen"])

    assert "2 unclipped coupon(s)" in result.output


def test_filters_apply_to_clipping_not_just_dry_run(runner, no_network, monkeypatch):
    seen = {}

    def capture(_http, _banner, items, **kwargs):
        seen["ids"] = [c["id"] for c in items]
        return summary()

    monkeypatch.setattr(coupons, "list_by_status", lambda *_: fake_coupons(4))
    monkeypatch.setattr(coupons, "apply_all", capture)
    runner.invoke(cli.main, ["clip", "--department", "Dairy"])

    assert seen["ids"] == ["c0", "c2"]


def test_list_filters_shows_the_vocabulary(runner, no_network, monkeypatch):
    monkeypatch.setattr(coupons, "list_by_status", lambda *_: fake_coupons(4))
    monkeypatch.setattr(
        coupons, "apply_all", lambda *a, **k: pytest.fail("--list-filters must not clip")
    )

    result = runner.invoke(cli.main, ["clip", "--list-filters"])

    assert result.exit_code == 0
    assert "Dairy" in result.output
    assert "IN_STORE" in result.output


def test_list_filters_json(runner, no_network, monkeypatch):
    monkeypatch.setattr(coupons, "list_by_status", lambda *_: fake_coupons(4))

    payload = json.loads(runner.invoke(cli.main, ["clip", "--list-filters", "--json"]).output)

    assert payload["departments"] == {"Dairy": 2, "Frozen": 2}
    assert payload["waysToShop"] == {"IN_STORE": 4}


def test_a_filter_matching_nothing_clips_nothing_and_says_so(runner, no_network, monkeypatch):
    monkeypatch.setattr(coupons, "list_by_status", lambda *_: fake_coupons(4))

    result = runner.invoke(cli.main, ["clip", "--dry-run", "--department", "Nonexistent"])

    assert result.exit_code == 0
    assert "0 of 4 coupon(s) match" in result.output


def test_unclip_enumerates_clipped_not_unclipped(runner, no_network, monkeypatch):
    """Unclipping the unclipped list would be a no-op against the wrong coupons."""
    asked = {}

    def by_status(_http, _banner, status):
        asked["status"] = status
        return fake_coupons(2)

    monkeypatch.setattr(coupons, "list_by_status", by_status)
    monkeypatch.setattr(coupons, "apply_all", lambda *a, **k: summary())
    runner.invoke(cli.main, ["unclip", "--yes"])

    assert asked["status"] == coupons.CLIPPED


def test_clip_enumerates_unclipped(runner, no_network, monkeypatch):
    asked = {}

    def by_status(_http, _banner, status):
        asked["status"] = status
        return fake_coupons(2)

    monkeypatch.setattr(coupons, "list_by_status", by_status)
    monkeypatch.setattr(coupons, "apply_all", lambda *a, **k: summary())
    runner.invoke(cli.main, ["clip"])

    assert asked["status"] == coupons.UNCLIPPED


def test_unclip_passes_the_unclip_action(runner, no_network, monkeypatch):
    seen = {}

    def capture(*_a, **kwargs):
        seen.update(kwargs)
        return summary()

    monkeypatch.setattr(coupons, "list_by_status", lambda *_: fake_coupons(2))
    monkeypatch.setattr(coupons, "apply_all", capture)
    runner.invoke(cli.main, ["unclip", "--yes"])

    assert seen["action"] == coupons.UNCLIP


def test_unclip_asks_before_removing(runner, no_network, monkeypatch):
    monkeypatch.setattr(coupons, "list_by_status", lambda *_: fake_coupons(3))
    monkeypatch.setattr(
        coupons, "apply_all", lambda *a, **k: pytest.fail("must not act after a refusal")
    )

    result = runner.invoke(cli.main, ["unclip"], input="n\n")

    assert result.exit_code == 0
    assert "Cancelled" in result.output


def test_unclip_yes_skips_the_prompt(runner, no_network, monkeypatch):
    monkeypatch.setattr(coupons, "list_by_status", lambda *_: fake_coupons(3))
    monkeypatch.setattr(coupons, "apply_all", lambda *a, **k: summary())

    result = runner.invoke(cli.main, ["unclip", "--yes"])

    assert result.exit_code == 0
    assert "Removed" in result.output


def test_clip_never_prompts(runner, no_network, monkeypatch):
    """Clipping is additive; only removal needs confirming."""
    monkeypatch.setattr(coupons, "list_by_status", lambda *_: fake_coupons(3))
    monkeypatch.setattr(coupons, "apply_all", lambda *a, **k: summary())

    result = runner.invoke(cli.main, ["clip"])

    assert result.exit_code == 0
    assert "Remove" not in result.output


def test_unclip_honours_filters(runner, no_network, monkeypatch):
    seen = {}

    def capture(_http, _banner, items, **kwargs):
        seen["ids"] = [c["id"] for c in items]
        return summary()

    monkeypatch.setattr(coupons, "list_by_status", lambda *_: fake_coupons(4))
    monkeypatch.setattr(coupons, "apply_all", capture)
    runner.invoke(cli.main, ["unclip", "--yes", "--department", "Dairy"])

    assert seen["ids"] == ["c0", "c2"]


def test_unclip_dry_run_changes_nothing(runner, no_network, monkeypatch):
    monkeypatch.setattr(coupons, "list_by_status", lambda *_: fake_coupons(2))
    monkeypatch.setattr(coupons, "apply_all", lambda *a, **k: pytest.fail("dry run must not act"))

    result = runner.invoke(cli.main, ["unclip", "--dry-run"])

    assert result.exit_code == 0
    assert "2 clipped coupon(s)" in result.output


def test_nothing_to_do_is_not_an_error(runner, no_network, monkeypatch):
    monkeypatch.setattr(coupons, "list_by_status", lambda *_: [])
    monkeypatch.setattr(coupons, "apply_all", lambda *a, **k: pytest.fail("nothing to act on"))

    result = runner.invoke(cli.main, ["unclip", "--yes"])

    assert result.exit_code == 0
    assert "Nothing to do" in result.output


def test_login_is_listed_last(runner):
    """clip and unclip are the everyday pair; login is setup and should not split them."""
    out = runner.invoke(cli.main, ["--help"], prog_name="kroger-clipper").output

    order = [out.index(f"kroger-clipper {name}:") for name in ("clip", "unclip", "login")]
    assert order == sorted(order)


def _kept(runner, monkeypatch, args):
    monkeypatch.setattr(coupons, "list_by_status", lambda *_: fake_coupons(4))
    out = runner.invoke(cli.main, ["clip", "--dry-run", *args]).output
    return [ln.strip().split(":")[0] for ln in out.splitlines() if ln.startswith("  ")]


def test_comma_separated_values(runner, no_network, monkeypatch):
    """fake_coupons alternates Dairy/Frozen, so both departments means everything."""
    assert len(_kept(runner, monkeypatch, ["--department", "Dairy,Frozen"])) == 4


def test_repeated_options_still_work(runner, no_network, monkeypatch):
    assert len(_kept(runner, monkeypatch, ["--department", "Dairy", "--department", "Frozen"])) == 4


def test_commas_and_repeats_can_be_mixed(runner, no_network, monkeypatch):
    args = ["--department", "Dairy,Nonexistent", "--department", "Frozen"]
    assert len(_kept(runner, monkeypatch, args)) == 4


def test_whitespace_around_commas_is_ignored(runner, no_network, monkeypatch):
    assert len(_kept(runner, monkeypatch, ["--department", " Dairy , Frozen "])) == 4


def test_empty_segments_are_dropped(runner, no_network, monkeypatch):
    """A trailing comma must not become an empty department that matches nothing."""
    assert len(_kept(runner, monkeypatch, ["--department", "Dairy,,"])) == 2


def test_a_department_with_spaces_and_an_ampersand(runner, no_network, monkeypatch):
    catalogue = [
        {"id": "a", "brandName": "X", "shortDescription": "s", "categories": ["Health & Beauty"]},
        {"id": "b", "brandName": "Y", "shortDescription": "t", "categories": ["Dairy"]},
    ]
    monkeypatch.setattr(coupons, "list_by_status", lambda *_: catalogue)

    result = runner.invoke(cli.main, ["clip", "--dry-run", "--department", "Health & Beauty"])

    assert "1 of 2 coupon(s) match" in result.output


def test_ways_to_shop_filter(runner, no_network, monkeypatch):
    catalogue = [
        {"id": "a", "brandName": "X", "shortDescription": "s", "modalities": ["IN_STORE"]},
        {"id": "b", "brandName": "Y", "shortDescription": "t", "modalities": ["DELIVERY"]},
        {"id": "c", "brandName": "Z", "shortDescription": "u", "modalities": ["PICKUP"]},
    ]
    monkeypatch.setattr(coupons, "list_by_status", lambda *_: catalogue)

    result = runner.invoke(cli.main, ["clip", "--dry-run", "--ways-to-shop", "IN_STORE,PICKUP"])

    assert "2 of 3 coupon(s) match" in result.output


def test_ways_to_shop_works_on_unclip_too(runner, no_network, monkeypatch):
    monkeypatch.setattr(coupons, "list_by_status", lambda *_: fake_coupons(2))
    monkeypatch.setattr(coupons, "apply_all", lambda *a, **k: summary())

    result = runner.invoke(cli.main, ["unclip", "--yes", "--ways-to-shop", "IN_STORE"])

    assert result.exit_code == 0
