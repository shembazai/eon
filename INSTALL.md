# EON — Rocky Linux headless install

Reproducible install for EON on a Rocky Linux 10+ headless host, aligned with
[SIM](../SIM/README.md) conventions (`/opt/k1` layout, structured health checks,
verify scripts).

Authority: [K1_constitution.txt](../K1_constitution.txt) (local-first, explicit state).

## Requirements

| Item | Minimum |
| --- | --- |
| OS | Rocky Linux 10+ (or compatible RHEL-like) |
| Python | 3.10+ (3.12 recommended; matches SIM) |
| Network | Not required for core deterministic mode |
| Disk | Writable `/opt/k1` (or custom paths via env vars) |

Core EON has no compiled dependencies. Optional extras:

| Extra | Package | Notes |
| --- | --- | --- |
| `charts` | matplotlib | Profile charts in interactive menu |
| `ai` | llama-cpp-python | Local GGUF inference; may need `gcc`, `cmake` |

## Option A — Standalone EON (finance-only host)

```bash
cd /path/to/K1/EON
sudo mkdir -p /opt/k1/data/eon /opt/k1/logs
sudo chown -R "$USER:$USER" /opt/k1/data/eon /opt/k1/logs

python3 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
python -m pip install -e ".[dev]"

export K1_EON_DATA_DIR=/opt/k1/data/eon
export K1_EON_LOG_DIR=/opt/k1/logs

eon --version
eon health --json
./scripts/verify.sh
```

Create a profile (first run):

```bash
eon menu    # choose option 1 — Create / update profile
```

Or copy an existing `profile.json` into `$K1_EON_DATA_DIR`.

## Option B — K1 runtime with FinanceAgent

Install EON as an optional K1 extra from the repository root:

```bash
cd /path/to/K1
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
python -m pip install -e ".[dev,finance]"

export K1_EON_DATA_DIR=/opt/k1/data/eon
export K1_EON_LOG_DIR=/opt/k1/logs
export K1_RUNTIME_TASK_STATE=/opt/k1/logs/task-lifecycle.json

eon health --json
pytest -q tests/test_generated_agents.py -k finance
```

`FinanceAgent` delegates in-scope tasks to `eon.bridge.query_finance_task` when
the `eon` package is installed.

## Option C — Scripted install (SIM-provisioned host)

After SIM has created the K1 directory layout (`sim phase2-init`):

```bash
cd /path/to/K1/EON
./scripts/install_headless.sh
```

The script creates `/opt/k1/data/eon` and `/opt/k1/logs`, installs EON in a
local venv, runs `eon health` and `./scripts/verify.sh`.

Override paths:

```bash
K1_EON_DATA_DIR=/data/eon K1_EON_LOG_DIR=/var/log/eon ./scripts/install_headless.sh
```

## Environment variables

| Variable | Default (K1 layout) | Purpose |
| --- | --- | --- |
| `K1_EON_DATA_DIR` | — | Profile, journal, reports |
| `K1_EON_LOG_DIR` | `/opt/k1/logs` | `eon.log` and task audit log |
| `K1_EON_TASK_LOG` | `$K1_EON_LOG_DIR/eon-task-log.jsonl` | JSONL task audit (Phase B) |
| `K1_MODELS_DIR` | `/opt/k1/models` | GGUF models (optional AI) |
| `EON_PFA_BASE_DIR` | `~/AI` | Legacy layout when `K1_EON_DATA_DIR` unset |

## Verification checklist

```bash
eon health              # operator dashboard
eon health --json       # monitoring-friendly output
eon self-test           # 25 regression checks
eon query "what are my monthly expenses?"
eon logs --json -n 5    # recent task audit entries
cd K1/EON && ./scripts/verify.sh   # pytest + self-test gate
```

Expected: `health` reports `ok` or `degraded` (warnings for missing profile/charts/AI
are acceptable). `self-test` must show `25/25 passed`.

## Optional extras

```bash
# From K1/EON venv
pip install -e ".[charts]"
pip install -e ".[ai]"    # may require: dnf install gcc cmake
```

## Coexistence with SIM

| Subsystem | Data root | CLI | Role |
| --- | --- | --- | --- |
| SIM | manifest + SQLite state | `sim` | Infrastructure reconciliation |
| EON | `/opt/k1/data/eon` | `eon` | Personal finance control plane |

Both use `/opt/k1/logs` for operator logs. SIM phase reports and EON task audit
logs are separate files and do not conflict.

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| `no_profile` on query | Run `eon menu` option 1 or set `K1_EON_DATA_DIR` to a dir with `profile.json` |
| `task_log_writable` warning | `sudo chown` on `K1_EON_LOG_DIR` or set `K1_EON_TASK_LOG` to a writable path |
| `FinanceAgent` shows `eon_available: false` | `pip install -e ".[finance]"` from K1 root |
| `python: command not found` in verify.sh | `PYTHON=python3 ./scripts/verify.sh` or activate venv first |

## Legacy shim

`~/AI/finance/EON_PFA.py` remains for existing workflows. It delegates to the
`K1/EON` package when present on `PYTHONPATH`.
