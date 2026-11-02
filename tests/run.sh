#!/usr/bin/env sh
# One repository entry point, shared with GitHub Actions.
set -eu
root="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
if [ -n "${STACKPLAN_PYTHON:-}" ]; then
    python_command="$STACKPLAN_PYTHON"
elif [ -x "$root/.venv/bin/python" ]; then
    python_command="$root/.venv/bin/python"
else
    python_command=python3
fi
mode="${1:-full}"
case "$mode" in
    all) mode=full ;;
    workflow) mode=integration ;;
esac
exec "$python_command" "$root/tests/verify.py" "$mode"
