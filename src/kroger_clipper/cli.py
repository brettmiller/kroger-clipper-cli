import json
import sys

import click

from . import coupons, errors, transport
from . import session as session_mod

EXIT_SESSION_EXPIRED = 2
EXIT_STRUCTURAL = 3
EXIT_BLOCKED = 4


@click.group()
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
    click.echo(f"Coupons API probe: HTTP {probe['status']}")
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
@click.option("--json", "as_json", is_flag=True, help="Machine-readable output on stdout.")
def clip(banner: str, dry_run: bool, as_json: bool) -> None:
    """Clip every unclipped digital coupon."""
    if not dry_run:
        click.echo("Clipping is not implemented yet. Re-run with --dry-run.", err=True)
        sys.exit(EXIT_STRUCTURAL)

    try:
        http = transport.build(banner)
        found = coupons.list_unclipped(http, banner)
    except errors.SessionMissing as exc:
        click.echo(f"{exc}. Run `kroger-clipper login`.", err=True)
        sys.exit(EXIT_SESSION_EXPIRED)
    except errors.Blocked as exc:
        click.echo(f"Kroger refused the request: {exc}. Wait before retrying.", err=True)
        sys.exit(EXIT_BLOCKED)
    except errors.StructuralError as exc:
        click.echo(f"The API did not look as expected: {exc}", err=True)
        sys.exit(EXIT_STRUCTURAL)

    if as_json:
        click.echo(json.dumps([_summarise(c) for c in found], indent=2))
        return

    click.echo(f"{len(found)} unclipped coupon(s)")
    for coupon in found:
        click.echo(f"  {coupons.describe(coupon)}")


def _summarise(coupon: dict) -> dict:
    return {
        "id": coupon.get("id"),
        "krogerCouponNumber": coupon.get("krogerCouponNumber"),
        "brand": coupon.get("brandName") or coupon.get("brand"),
        "description": coupon.get("shortDescription") or coupon.get("title"),
        "expirationDate": coupon.get("expirationDate"),
    }
