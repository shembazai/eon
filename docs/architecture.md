# EON Architecture

EON is a deterministic, local-first personal finance subsystem for K1.

Foundation doctrine: [EON_constitution.txt](../EON_constitution.txt)
(parent: [K1_constitution.txt](../../K1_constitution.txt)).

## Components

| Module | Responsibility |
| --- | --- |
| `eon.pfa_engine` | Core logic: profile, forecast, decision, mutation firewall |
| `eon.config` | Path resolution (`K1_EON_DATA_DIR`, legacy `~/AI` layout) |
| `eon.health` | Startup/operator health checks |
| `eon.bridge` | Agent-facing programmatic API |
| `eon.cli` | Typer CLI (`eon health`, `eon query`, `eon self-test`) |
| `eon.logger` | Structured logging (console, file, journald best-effort) |
| `eon.task_log` | JSONL task audit log per bridge invocation (K1 §14.5) |

## Data flow

```text
User / FinanceAgent
    → eon.bridge.query_finance_task (or CLI)
    → deterministic router (run_deterministic_engine)
    → profile.json + change_journal.csv
    → optional LLM fallback (interactive Local AI only)
```

## Agent contract mapping (constitution §4.2)

| Field | EON value |
| --- | --- |
| name | `eon` (tool) / `finance` (K1 agent) |
| purpose | Personal financial decision support |
| inputs | Natural-language prompts, structured profile |
| outputs | Deterministic answers, forecasts, advice, journal entries |
| limitations | Personal-only; no remote AI by default; no encryption yet |
| tools | JSON I/O, CSV journal, optional matplotlib, optional llama-cpp |
| memory | `profile.json`, `change_journal.csv`, `profile_last_backup.json` |

## Relationship to SIM

SIM maintains **infrastructure** declared state. EON maintains **personal finance**
declared state. Both favor observation, evidence, and human-auditable change logs.
