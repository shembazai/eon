# EON Security

## Foundation

EON is built from a security-first perspective aligned with
[EON_constitution.txt](../EON_constitution.txt) and
[K1_constitution.txt](../../K1_constitution.txt) (local-first, explicit state,
human strategic authority).

The goal is not only to protect data, but to ensure that the system remains:

- understandable
- predictable
- controllable

## Principles

- Local data ownership
- Explicit state changes
- Deterministic behavior
- Backup before mutation
- Traceable changes (CSV change journal)

## K1 integration

- FinanceAgent delegates through `eon.bridge` — least-privilege tool access
- `eon health --json` exposes operator-visible state without hidden failures
- Optional AI and charts degrade gracefully; core mode needs no network

## Philosophy

Security is not only about preventing attacks.  
It is about ensuring that the user can trust and understand the system at all times.
