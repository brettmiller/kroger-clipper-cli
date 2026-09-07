import json
import sys
from pathlib import Path

import click

from . import coupons, errors, scrub, select, transport
from . import session as session_mod

EXIT_SESSION_EXPIRED = 2
EXIT_STRUCTURAL = 3
EXIT_BLOCKED = 4


class DetailedGroup(click.Group):
    """Show each subcommand's own options in the top-level help.

    Click lists only names and one-line summaries, so finding --dry-run or
    --max-clips takes a second command. There are two subcommands; showing them
    in full costs a dozen lines and saves the round trip.
    """

    def list_commands(self, ctx: click.Context) -> list[str]:
        # login is setup you run rarely; clip and unclip are the everyday pair and
        # belong next to each other, in both the summary and the expansions.
        return sorted(super().list_commands(ctx), key=lambda name: (name == "login", name))

    def format_help(self, ctx: click.Context, formatter: click.HelpFormatter) -> None:
        super().format_help(ctx, formatter)
        for name in self.list_commands(ctx):
            command = self.get_command(ctx, name)
            if command is None or command.hidden:
                continue
            self._format_subcommand(ctx, formatter, name, command)

    @staticmethod
    def _format_subcommand(ctx, formatter, name, command) -> None:
        sub_ctx = click.Context(command, info_name=name, parent=ctx)
        # Filter on the visible flag, not the param name: click names its help
        # option inconsistently across versions ("_click_default_help" in 8.5).
        rows = [
            record
            for param in command.get_params(sub_ctx)
            if (record := param.get_help_record(sub_ctx)) and record[0] != "--help"
        ]
        with formatter.section(f"{ctx.info_name} {name}"):
            if command.help:
                formatter.write_text(command.help.strip().splitlines()[0])
                formatter.write_paragraph()
            if rows:
                formatter.write_dl(rows)


@click.group(cls=DetailedGroup)
# The distribution is kroger-clipper-cli but the import package is
# kroger_clipper; click guesses the latter and fails to find it.
@click.version_option(package_name="kroger-clipper-cli")
def main() -> None:
    """Clip Kroger digital coupons from the command line."""


@main.command()
@click.option(
    "--banner", default="kroger.com", show_default=True, help="Kroger-owned banner domain."
)
def login(banner: str) -> None:
    """Sign in interactively and capture the session."""
    click.echo(f"Opening Chrome for {banner}. Sign in, then leave the window alone.", err=True)
    try:
        result = session_mod.login(banner)
    except session_mod.ChromeNotFound as exc:
        click.echo(str(exc), err=True)
        sys.exit(EXIT_STRUCTURAL)
    except session_mod.Blocked as exc:
        click.echo(f"Kroger refused the connection: {exc}.", err=True)
        click.echo(
            "Wait for it to clear before retrying; repeated attempts make it worse.", err=True
        )
        sys.exit(EXIT_BLOCKED)
    except session_mod.SignInAbandoned as exc:
        click.echo(f"Sign-in did not complete: {exc}", err=True)
        sys.exit(EXIT_SESSION_EXPIRED)

    click.echo(f"Session saved to {result['session_file']}")
    click.echo(f"Cookies captured ({len(result['cookies'])}): {', '.join(result['cookies'])}")

    warm = result["warm"]
    if not warm["ok"]:
        click.echo(f"Warm-up failed ({warm['detail']}) — session saved but unverified.", err=True)
        click.echo("Wait for the block to clear before retrying; do not hammer it.", err=True)
        sys.exit(EXIT_BLOCKED)

    click.echo(f"Store headers captured: {', '.join(result['context_headers'])}")
    probe = result["probe"]
    # Enumeration works without cookies, so this proves the store headers work,
    # not that we are signed in. Authentication only shows up at clip time.
    click.echo(f"Coupons API probe: HTTP {probe['status']} (store headers, not auth)")
    if not probe.get("ok"):
        detail = probe.get("snippet")
        if detail is None:
            detail = probe.get("error")
        click.echo(f"  response: {detail if detail else '(empty body)'}", err=True)
        click.echo("  (session is saved; the API call itself did not succeed)", err=True)


def _csv(_ctx, _param, value: tuple[str, ...]) -> tuple[str, ...]:
    """Accept `--x a,b` as well as `--x a --x b`, and any mix of the two."""
    return tuple(part.strip() for item in value for part in item.split(",") if part.strip())


def _shared_options(command):
    """Options both directions need. Two commands, one vocabulary."""
    for option in reversed(
        (
            click.option(
                "--banner",
                default="kroger.com",
                show_default=True,
                help="Kroger-owned banner domain.",
            ),
            click.option("--dry-run", is_flag=True, help="Show what would change; change nothing."),
            click.option(
                "--department",
                "departments",
                multiple=True,
                callback=_csv,
                help="Only these departments, comma-separated.",
            ),
            click.option(
                "--exclude-department",
                "exclude_departments",
                multiple=True,
                callback=_csv,
                help="Skip these departments, comma-separated.",
            ),
            click.option(
                "--ways-to-shop",
                "ways_to_shop",
                multiple=True,
                callback=_csv,
                help="Only these, comma-separated: IN_STORE, PICKUP, DELIVERY.",
            ),
            click.option(
                "--list-filters",
                is_flag=True,
                help="Show the departments and ways to shop on offer, then exit.",
            ),
            click.option(
                "--delay",
                nargs=2,
                type=float,
                default=coupons.DELAY_RANGE_S,
                show_default=True,
                metavar="MIN MAX",
                help="Seconds to pause between requests, chosen at random in this range.",
            ),
            click.option(
                "--json", "as_json", is_flag=True, help="Machine-readable output on stdout."
            ),
        )
    ):
        command = option(command)
    return command


@main.command()
@_shared_options
@click.option("--max-clips", "limit", type=int, default=None, help="Stop after this many coupons.")
def clip(**kwargs) -> None:
    """Clip every unclipped digital coupon."""
    _run(coupons.CLIP, **kwargs)


@main.command()
@_shared_options
@click.option("--limit", type=int, default=None, help="Stop after this many coupons.")
@click.option("--yes", "assume_yes", is_flag=True, help="Skip the confirmation prompt.")
def unclip(**kwargs) -> None:
    """Remove coupons from the card.

    Useful for resetting before a filtered clip: the card holds a limited number
    of coupons, so what is already on it decides what will fit.
    """
    _run(coupons.UNCLIP, **kwargs)


# Wording only. The mechanics are identical in both directions.
_VERBS = {
    coupons.CLIP: ("Clipping", "Clipped", "unclipped", "were already on the card"),
    coupons.UNCLIP: ("Removing", "Removed", "clipped", "were not on the card"),
}


def _run(
    action: str,
    banner: str,
    dry_run: bool,
    departments: tuple[str, ...],
    exclude_departments: tuple[str, ...],
    ways_to_shop: tuple[str, ...],
    list_filters: bool,
    limit: int | None,
    delay: tuple[float, float],
    as_json: bool,
    assume_yes: bool = True,
) -> None:
    gerund, past, noun, already_phrase = _VERBS[action]

    try:
        http, found = _connect(banner, action)
    except _Stale as stale:
        if not _relogin(stale.reason, banner):
            sys.exit(stale.exit_code)
        try:
            http, found = _connect(banner, action)
        except _Stale as again:
            click.echo(f"Still refused after signing in: {again.reason}", err=True)
            sys.exit(again.exit_code)

    if list_filters:
        _show_filters(found, as_json)
        return

    total = len(found)
    found = select.select(
        found,
        departments=departments,
        exclude_departments=exclude_departments,
        ways_to_shop=ways_to_shop,
    )
    if len(found) != total and not as_json:
        click.echo(f"{len(found)} of {total} coupon(s) match the filters.", err=True)

    if dry_run:
        if as_json:
            click.echo(json.dumps([_summarise(c) for c in found], indent=2))
            return
        click.echo(f"{len(found)} {noun} coupon(s)")
        for coupon in found:
            click.echo(f"  {coupons.describe(coupon)}")
        return

    target = min(len(found), limit) if limit else len(found)
    if not target:
        click.echo(f"Nothing to do: no {noun} coupons matched.")
        return

    # Unclipping throws away work and cannot be undone without re-clipping, so it
    # asks first. Clipping is additive and does not.
    needs_confirm = not assume_yes and not as_json
    if needs_confirm and not click.confirm(
        f"Remove {target} coupon(s) from the card?", default=True, err=True
    ):
        click.echo("Cancelled.", err=True)
        return

    show_progress = sys.stderr.isatty() and not as_json
    seen = 0

    def report(outcome: dict) -> None:
        nonlocal seen
        seen += 1
        if not outcome["ok"]:
            click.echo(
                f"  failed {outcome['id']}: HTTP {outcome['status']} {outcome['body']}", err=True
            )
        elif show_progress:
            # Carriage return, no newline: one live line rather than 250 of scroll.
            click.echo(f"  {seen}/{target}\r", nl=False, err=True)

    click.echo(f"{gerund} {target} of {len(found)} {noun} coupon(s)...", err=True)
    try:
        result = coupons.apply_all(
            http,
            banner,
            found,
            action=action,
            limit=limit,
            delay_range=delay,
            on_result=None if as_json else report,
        )
    except ValueError as exc:
        click.echo(str(exc), err=True)
        sys.exit(EXIT_STRUCTURAL)
    except errors.SessionExpired as exc:
        click.echo(f"{exc}. Run `kroger-clipper login`.", err=True)
        sys.exit(EXIT_SESSION_EXPIRED)
    except errors.Blocked as exc:
        click.echo(f"Kroger refused the request: {exc}. Stopping.", err=True)
        sys.exit(EXIT_BLOCKED)

    if show_progress:
        click.echo(" " * 40 + "\r", nl=False, err=True)

    if as_json:
        click.echo(json.dumps(result, indent=2))
    else:
        click.echo(f"{past} {result['succeeded']} of {result['attempted']} attempted.")
        if result["already_done"]:
            click.echo(f"{result['already_done']} {already_phrase}.")
        if result["card_full"]:
            click.echo("Card is full — Kroger's per-card coupon limit was reached.")
        if result["failures"]:
            click.echo(f"{len(result['failures'])} failed.", err=True)

    if result["stopped"]:
        click.echo(f"Stopped early: {result['stopped']}", err=True)
        sys.exit(EXIT_STRUCTURAL)


class _Stale(Exception):
    """A failure that signing in again might fix."""

    def __init__(self, reason: str, exit_code: int):
        super().__init__(reason)
        self.reason = reason
        self.exit_code = exit_code


def _connect(banner: str, action: str):
    """Build a client and enumerate, translating failures into exits or a retry."""
    try:
        http = transport.build(banner)
        status = coupons.UNCLIPPED if action == coupons.CLIP else coupons.CLIPPED
        return http, coupons.list_by_status(http, banner, status)
    except (errors.SessionMissing, errors.SessionExpired) as exc:
        raise _Stale(str(exc), EXIT_SESSION_EXPIRED) from exc
    except errors.ConnectionReset as exc:
        raise _Stale(str(exc), EXIT_BLOCKED) from exc
    except errors.Blocked as exc:
        # A rate limit is not fixed by signing in, and retrying makes it worse.
        click.echo(f"Kroger refused the request: {exc}. Wait before retrying.", err=True)
        sys.exit(EXIT_BLOCKED)
    except errors.StructuralError as exc:
        click.echo(f"The API did not look as expected: {exc}", err=True)
        sys.exit(EXIT_STRUCTURAL)


def _interactive() -> bool:
    """Is there a human here to answer a prompt and sign in?"""
    return sys.stdin.isatty() and sys.stderr.isatty()


def _relogin(reason: str, banner: str) -> bool:
    """Offer to sign in again. Never opens a browser with nobody watching."""
    click.echo(reason, err=True)
    if not _interactive():
        click.echo("Run `kroger-clipper login`.", err=True)
        return False
    if not click.confirm("Sign in again now?", default=True, err=True):
        return False

    try:
        session_mod.login(banner)
    except errors.KrogerClipperError as exc:
        click.echo(f"Sign-in failed: {exc}", err=True)
        return False
    return True


def _show_filters(found: list[dict], as_json: bool) -> None:
    """Print the vocabulary. Guessing a department name is not a usable interface.

    All three of Kroger's filter fields are reported, including the one that is
    not filterable, because which UI section each field backs is unverified.
    """
    groups = (
        ("Departments", "departments", select.DEPARTMENTS, "--department"),
        ("Ways to shop", "waysToShop", select.WAYS_TO_SHOP, "--ways-to-shop"),
        ("Special savings", "specialSavings", select.SPECIAL_SAVINGS, "not filterable"),
    )
    counted = [
        (label, key, flag, field, select.tally(found, field)) for label, key, field, flag in groups
    ]

    if as_json:
        click.echo(json.dumps({key: counts for _l, key, _f, _fl, counts in counted}, indent=2))
        return

    for label, _key, flag, field, counts in counted:
        click.echo(f"{label} ({flag}, field {field}) — {len(counts)}:")
        for name, count in counts.items():
            click.echo(f"  {count:>4}  {name}")
        if not counts:
            click.echo("  (none)")
        click.echo()


def _summarise(coupon: dict) -> dict:
    return {
        "id": coupon.get("id"),
        "krogerCouponNumber": coupon.get("krogerCouponNumber"),
        "brand": coupon.get("brandName") or coupon.get("brand"),
        "description": coupon.get("shortDescription") or coupon.get("title"),
        "expirationDate": coupon.get("expirationDate"),
    }


@main.command(hidden=True)
@click.option(
    "--banner", default="kroger.com", show_default=True, help="Kroger-owned banner domain."
)
@click.option("--size", default=5, show_default=True, help="Coupons to capture.")
def capture(banner: str, size: int) -> None:
    """Record a real response as a scrubbed test fixture."""
    root = Path(__file__).resolve().parents[2]
    raw_path = root / "tests" / "captures" / "coupons_page.json"
    fixture_path = root / "tests" / "fixtures" / "coupons_page.json"

    try:
        http = transport.build(banner)
        payload = coupons.fetch_page(http, banner, offset=0, size=size)
    except (errors.SessionMissing, errors.SessionExpired) as exc:
        click.echo(f"{exc}. Run `kroger-clipper login`.", err=True)
        sys.exit(EXIT_SESSION_EXPIRED)
    except errors.Blocked as exc:
        click.echo(f"Kroger refused the request: {exc}. Wait before retrying.", err=True)
        sys.exit(EXIT_BLOCKED)

    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.write_text(json.dumps(payload, indent=2))

    try:
        scrubbed = scrub.scrub_payload(payload)
    except scrub.UnknownField as exc:
        click.echo(f"Refusing to write a fixture: {exc}", err=True)
        click.echo(f"The raw capture is at {raw_path} (gitignored).", err=True)
        sys.exit(EXIT_STRUCTURAL)

    fixture_path.parent.mkdir(parents=True, exist_ok=True)
    fixture_path.write_text(json.dumps(scrubbed, indent=2, sort_keys=True) + "\n")
    click.echo(f"Wrote {fixture_path} ({len(scrubbed['data']['coupons'])} coupons)")
