#!/usr/bin/env bash
# CI / operator gate: pytest + inline regression harness
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$script_dir/.."

PYTHON="${PYTHON:-python3}"
"$PYTHON" -m pytest -q
"$PYTHON" -m eon.cli self-test
