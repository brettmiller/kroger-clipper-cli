# Authentication is interactive-only; the password is never stored

Signing in requires a human: a `login` command opens a real browser, the person
authenticates through Kroger's identity provider, and only the resulting Session
is persisted to disk. The account password is never written anywhere by this
tool.

## Consequences

This tool cannot run unattended. When the Session expires, `clip` exits with
status 2 and instructs the user to run `login` again; a scheduled invocation
would simply fail until a human intervenes.

That is a deliberate trade. Unattended operation would require storing a
reusable credential, and the project this one replaces kept a plaintext password
in a config file on disk — the exact failure being designed out. Running weekly
is expected to keep the Session alive in practice.

If scheduling later becomes worth the cost, the decision to revisit is
credential storage (OS keychain, not a file), and it should supersede this ADR
rather than being bolted on quietly.
