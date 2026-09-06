class KrogerClipperError(Exception):
    pass


class SessionMissing(KrogerClipperError):
    pass


class SignInAbandoned(KrogerClipperError):
    pass


class ChromeNotFound(KrogerClipperError):
    pass


class SessionExpired(KrogerClipperError):
    """A session exists on disk but Kroger no longer accepts it."""


class Blocked(KrogerClipperError):
    """Kroger refused the request: rate limited, or Akamai denied it."""


class ConnectionReset(Blocked):
    """Refused below HTTP. Usually a stale session, sometimes a hard block."""


class StructuralError(KrogerClipperError):
    """The API did not look the way we depend on it looking."""
