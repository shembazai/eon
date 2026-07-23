# EON Roadmap — K1 Finance Control Plane

Foundation: [EON_constitution.txt](../EON_constitution.txt)
(parent: [K1_constitution.txt](../../K1_constitution.txt)).

Also aligned with [SIM/docs/ROADMAP.md](../../SIM/docs/ROADMAP.md) long-term vision.

## Current state (July 2026)

| Layer | Status |
| --- | --- |
| Deterministic engine (profile, forecast, decision) | Complete |
| Mutation firewall + CSV journal + undo | Complete |
| Regression harness (`eon self-test`, 25 checks) | Complete |
| K1 package (`K1/EON`, typer CLI, health) | Complete |
| FinanceAgent → EON bridge | Complete |
| Optional charts / Local AI | Complete (graceful degradation) |
| pytest suite | Complete (50 tests) |
| Distribution (.deb / unified K1 installer) | Not started |

## Completed — K1 integration (this pass)

1. **Canonical package** at `K1/EON/` (sibling to `K1/SIM/`)
2. **`eon health`** — operator dashboard with JSON output
3. **`K1_EON_DATA_DIR`** — K1 deployment path convention
4. **FinanceAgent** delegates in-scope tasks to `eon.bridge`
5. **Legacy shim** — `~/AI/finance/EON_PFA.py` preserved

## Next priorities

### Phase A — Test hardening
- Port inline regression cases to `tests/` with pytest — **complete** (36 tests)
- CI gate: `./scripts/verify.sh` (`pytest -q` + `eon self-test`) — **complete**

### Phase B — Observability
- Structured JSON task log per `query_finance_task` invocation — **complete**
- Align log fields with K1 alpha observability requirements — **complete**
- `eon logs` CLI for recent entries; `K1_EON_TASK_LOG` override

### Phase C — Packaging
- Optional `[finance]` extra on K1 `pyproject.toml` — **complete**
- Document Rocky Linux headless install alongside SIM — **complete** (`INSTALL.md`, `scripts/install_headless.sh`)

## Out of scope (this branch)

- Business finance profiles
- Remote AI by default
- Password / encryption at rest
- OCR / voice input

## Decision log

| Decision | Rationale |
| --- | --- |
| EON is a tool, not a K1 agent | Constitution §13.3 alpha agent cap |
| `K1/EON/` canonical home | SIM ROADMAP long-term vision |
| Keep monolithic `pfa_engine.py` for now | Simplicity; split modules in beta when contracts stabilize |
| `eon health --json` uses typer.echo | SIM precedent — Rich breaks JSON parsing |
