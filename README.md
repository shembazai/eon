# EON

EON is a local-first, deterministic-first personal financial assistant built for clarity, control, and structured financial decision-making.

Its behavior is designed to remain understandable: state is explicit, mutations are constrained, and core outputs are produced through deterministic logic before any optional AI layer is used.

---

## Why EON exists

Many financial tools become opaque as they become more automated.

EON takes the opposite approach. It prioritizes transparency, predictability, and user control. The goal is to keep financial reasoning legible, auditable, and stable while still allowing optional local AI support where deterministic logic does not apply.

---

## Current Scope

This release is focused on **personal finance only**.

Included in the current branch:

- Multi-income personal profiles
- Monthly income, expense, and savings estimation
- Budget breakdown and expense structuring
- Deterministic forecasting and goal projections
- Deterministic decision support
- Controlled profile mutation
- One-step undo
- CSV change journal
- Optional local chart generation
- Optional local AI fallback

Not included in this release:

- Business finance workflows
- Cloud or remote AI by default
- OCR pipelines
- Voice input
- Password or encryption features

---

## Core Design Principles

- Local-first operation
- Deterministic-first reasoning
- Explicit state
- Constrained mutation
- Auditable changes
- Graceful degradation when optional components are unavailable

---

## Repository Structure

```text
eon/
├── EON_PFA.py
├── run_eon.sh
├── install_core.sh
├── install_optional_charts.sh
├── install_optional_ai.sh
├── requirements-core.txt
├── requirements-charts.txt
├── requirements-ai.txt
├── INSTALL.md
├── DEMO_CASES.md
├── DISTRIBUTION.md
└── windows installer and packaging assets
```

---

## License

Custom license — personal, educational, and non-commercial use permitted. Commercial use requires written permission. See [LICENSE](LICENSE) and [docs/LICENSE.md](docs/LICENSE.md).

## Security

See [SECURITY.md](SECURITY.md) for vulnerability reporting.
