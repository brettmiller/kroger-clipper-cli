import sys

import click

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
