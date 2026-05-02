#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

echo "=== service-cartographer Setup ==="

check_command() {
    if ! command -v "$1" >/dev/null 2>&1; then
        echo "ERROR: $1 is required but not installed."
        exit 1
    fi
}

check_command python3

PYTHON_VERSION="$(python3 - <<'PY'
import sys
print(f"{sys.version_info.major}.{sys.version_info.minor}")
PY
)"

case "$PYTHON_VERSION" in
    3.11|3.12|3.13) ;;
    *)
        echo "ERROR: Python 3.11+ is required. Found $PYTHON_VERSION."
        exit 1
        ;;
esac

cd "$PROJECT_DIR"

if [ ! -d ".venv" ]; then
    python3 -m venv .venv
fi

# shellcheck disable=SC1091
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"

echo "=== Setup complete ==="
echo "Running verification..."
service-cartographer scan \
    --systemd-scope off \
    --no-cron \
    --repo-root "$PROJECT_DIR" \
    --wrapper-dir "$PROJECT_DIR/scripts" \
    --format json \
    | python3 -c 'import json, sys; data=json.load(sys.stdin); print("Scanned {} items".format(data["summary"]["total"]))'
