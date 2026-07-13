# Security Policy

## Philosophy

Shembazaï builds systems where security comes before convenience. If you find a vulnerability, report it responsibly so it can be fixed before it is exploited.

## Reporting a vulnerability

**Preferred:** [GitHub Security Advisories](https://github.com/Shembazai/eon/security/advisories/new) (private disclosure).

**Alternative:** shembazai@pm.me — include steps to reproduce, affected version, and impact assessment.

Please do not open public issues for exploitable security bugs.

## Scope

**In scope**

- Deterministic logic errors that could cause incorrect financial outputs
- Unauthorized mutation of financial state or audit logs
- Local data exposure through unintended file access
- Dependency vulnerabilities in shipped requirements files

**Out of scope**

- Missing encryption at rest (not claimed in current release)
- Optional AI components when not installed
- Social engineering or physical access attacks
- Issues in forks or third-party tools not maintained in this repository

## Response expectations

- Acknowledgment within 7 days for valid reports
- Fix or documented mitigation for confirmed issues affecting current release scope
- Credit in release notes if you wish (coordinated disclosure)

## Secure use

EON is designed for local-first, personal use. Run on systems you control. Review `INSTALL.md` before enabling optional AI components.
