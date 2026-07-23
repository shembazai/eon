# Security Policy

## Philosophy

Shembazaï builds systems where security comes before convenience. If you find a vulnerability, report it responsibly so it can be fixed before it is exploited.

## Reporting a vulnerability

**Preferred:** [GitHub Security Advisories](https://github.com/shembazai/eon/security/advisories/new) (private disclosure).

**Alternative:** shemba@shembazai.com — include steps to reproduce, affected version, and impact assessment.

Please do not open public issues for exploitable security bugs.

## Scope

**In scope**

- Deterministic logic errors that could cause incorrect financial outputs
- Unauthorized mutation of financial state or audit logs
- Bypass of mutation safety / confirmation gates
- Path or data-directory traversal outside declared EON data roots

**Out of scope**

- Operator misconfiguration of profiles or environment variables
- Third-party model / GGUF runtime issues outside EON's control
- Social engineering

## Response expectations

- Acknowledgment within 7 days for valid reports
- Fix or documented mitigation for confirmed issues
- Credit in release notes if you wish (coordinated disclosure)
