#!/usr/bin/env bash
# Reproducible headless install for EON on Rocky Linux / K1 hosts.
# See INSTALL.md for full documentation.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="${PYTHON:-python3}"
VENV_DIR="${VENV_DIR:-$ROOT/.venv}"
DATA_DIR="${K1_EON_DATA_DIR:-/opt/k1/data/eon}"
LOG_DIR="${K1_EON_LOG_DIR:-/opt/k1/logs}"

echo "==> EON headless install"
echo "    root:     $ROOT"
echo "    venv:     $VENV_DIR"
echo "    data:     $DATA_DIR"
echo "    logs:     $LOG_DIR"

if ! command -v "$PYTHON" >/dev/null 2>&1; then
  echo "error: $PYTHON not found" >&2
  exit 1
fi

if [[ ! -d "$DATA_DIR" || ! -w "$(dirname "$DATA_DIR")" ]]; then
  if command -v sudo >/dev/null 2>&1; then
    sudo mkdir -p "$DATA_DIR" "$LOG_DIR"
    sudo chown -R "${USER}:${USER}" "$DATA_DIR" "$LOG_DIR"
  else
    mkdir -p "$DATA_DIR" "$LOG_DIR"
  fi
else
  mkdir -p "$DATA_DIR" "$LOG_DIR"
fi

if [[ ! -d "$VENV_DIR" ]]; then
  "$PYTHON" -m venv "$VENV_DIR"
fi
# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"
python -m pip install -U pip
python -m pip install -e "$ROOT[dev]"

export K1_EON_DATA_DIR="$DATA_DIR"
export K1_EON_LOG_DIR="$LOG_DIR"

echo "==> eon --version"
eon --version

echo "==> eon health"
eon health || true

echo "==> verify gate"
PYTHON=python "$ROOT/scripts/verify.sh"

echo "==> install complete"
echo "    export K1_EON_DATA_DIR=$DATA_DIR"
echo "    export K1_EON_LOG_DIR=$LOG_DIR"
echo "    source $VENV_DIR/bin/activate"
