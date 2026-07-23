# EON

> **Lifecycle:** Alpha · **Role:** Commercial product (also K1 Tool Bus `eon.*`) · **Audience:** Personal finance (local-first)

EON is the **deterministic finance control plane** for [K1](https://github.com/shembazai/k1) — the counterpart to
[SIM](https://github.com/shembazai/sim) (infrastructure reconciliation). Both follow the
same operational patterns: explicit state, auditable changes, health checks,
and graceful degradation under partial failure.

Authority for governance and architecture:

- [K1 constitution](https://github.com/shembazai/k1/blob/main/K1_constitution.txt) — parent doctrine
- [EON_constitution.txt](EON_constitution.txt) — EON foundation (subordinate)

## Role in K1

| Layer | Component | Responsibility |
| --- | --- | --- |
| Capability | `FinanceCapability` | Scope checks, mission routing, structured outputs |
| Tool Bus | `eon.*` | `available` / `query` / `health` / `profile` ops |
| Tool / subsystem | **EON** | Deterministic finance engine, profile state, journal |
| Infrastructure | SIM | Host provisioning and IRE reconciliation |

EON is a **tool**, not a peer OS or user-facing agent. Missions reach it through
Mission Manager → Finance capability → Tool Bus.

## Design principles (constitution-aligned)

- **Local-first** — core mode needs no network or LLM
- **Deterministic-first** — math and routing before model fallback
- **Explicit state** — JSON profile, CSV change journal, one-step undo
- **Operational resilience** — `eon health`, structured logs, degraded modes
- **Modularity** — replaceable engine behind `eon.bridge` interface
- **Simplicity** — single personal-finance scope; no business branch in this release

## Install

Standalone:

```bash
cd EON   # or clone https://github.com/shembazai/eon
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

From K1 (enables Tool Bus `eon.*` / Finance capability):

```bash
cd K1
pip install -e ".[finance]"
```

Rocky Linux headless (alongside SIM): see [INSTALL.md](INSTALL.md) or
`./scripts/install_headless.sh`.

Optional extras:

```bash
pip install -e ".[charts]"   # matplotlib for View Profile charts
pip install -e ".[ai]"       # llama-cpp-python for Local AI
```

## Usage

```bash
eon health              # operator health dashboard
eon health --json       # machine-readable (monitoring-friendly)
eon self-test           # regression harness
eon query "what are my monthly expenses?"
eon logs --json -n 10    # recent task audit entries
eon menu                # interactive CLI
eon                     # same as menu when no subcommand
```

## Data paths

| Variable | Purpose |
| --- | --- |
| `K1_EON_DATA_DIR` | K1 deployment data root (profile, journal, reports) |
| `EON_PFA_BASE_DIR` | Legacy `~/AI`-style base (data under `<base>/finance/`) |
| `EON_PFA_MODEL_PATH` | Optional GGUF override for Local AI (else discover best local fit) |
| `K1_MODELS_DIR` | Model directory when using K1 layout |
| `K1_EON_LOG_DIR` | Log directory (default `/opt/k1/logs`) |
| `K1_EON_TASK_LOG` | Task audit JSONL (default `$K1_EON_LOG_DIR/eon-task-log.jsonl`) |

## K1 integration

With `pip install -e ".[finance]"` from the K1 tree, the Tool Bus adapter
`k1.tools.adapters.eon` exposes `eon.query` / `eon.health` / `eon.available`.
`FinanceCapability` routes personal-finance missions through that bus.
Without EON installed, finance missions degrade gracefully (`eon_available: false`).
