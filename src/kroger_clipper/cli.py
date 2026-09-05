import json
import sys
from pathlib import Path

import click

from . import coupons, errors, scrub, transport
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
@click.version_option()
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


@main.command()
@click.option(
    "--banner", default="kroger.com", show_default=True, help="Kroger-owned banner domain."
)
@click.option("--dry-run", is_flag=True, help="Enumerate unclipped coupons; clip nothing.")
@click.option("--max-clips", type=int, default=None, help="Stop after this many coupons.")
@click.option(
    "--delay",
    nargs=2,
    type=float,
    default=coupons.DELAY_RANGE_S,
    show_default=True,
    metavar="MIN MAX",
    help="Seconds to pause between clips, chosen at random in this range.",
)
@click.option("--json", "as_json", is_flag=True, help="Machine-readable output on stdout.")
def clip(
    banner: str,
    dry_run: bool,
    max_clips: int | None,
    delay: tuple[float, float],
    as_json: bool,
) -> None:
    """Clip every unclipped digital coupon."""
    try:
        http = transport.build(banner)
        found = coupons.list_unclipped(http, banner)
    except (errors.SessionMissing, errors.SessionExpired) as exc:
        click.echo(f"{exc}. Run `kroger-clipper login`.", err=True)
        sys.exit(EXIT_SESSION_EXPIRED)
    except errors.Blocked as exc:
        click.echo(f"Kroger refused the request: {exc}. Wait before retrying.", err=True)
        sys.exit(EXIT_BLOCKED)
    except errors.StructuralError as exc:
        click.echo(f"The API did not look as expected: {exc}", err=True)
        sys.exit(EXIT_STRUCTURAL)

    if dry_run:
        if as_json:
            click.echo(json.dumps([_summarise(c) for c in found], indent=2))
            return
        click.echo(f"{len(found)} unclipped coupon(s)")
        for coupon in found:
            click.echo(f"  {coupons.describe(coupon)}")
        return

    target = min(len(found), max_clips) if max_clips else len(found)
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
            click.echo(f"  {seen}/{target} clipped\r", nl=False, err=True)

    click.echo(f"Clipping {target} of {len(found)} unclipped coupon(s)...", err=True)
    try:
        result = coupons.clip_all(
            http,
            banner,
            found,
            limit=max_clips,
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
        click.echo(f"Clipped {result['clipped']} of {result['attempted']} attempted.")
        if result["already_clipped"]:
            click.echo(f"{result['already_clipped']} were already on the card.")
        if result["card_full"]:
            click.echo("Card is full — Kroger's per-card coupon limit was reached.")
        if result["failures"]:
            click.echo(f"{len(result['failures'])} failed.", err=True)

    if result["stopped"]:
        click.echo(f"Stopped early: {result['stopped']}", err=True)
        sys.exit(EXIT_STRUCTURAL)


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
