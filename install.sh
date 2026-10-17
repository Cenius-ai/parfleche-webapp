#!/usr/bin/env bash
# Parfleche setup: verify the interpreter, refresh pip tooling when the network
# allows it, then run an import self-check. Parfleche has no third-party runtime
# dependencies, so this script installs nothing and exits; the shell is started
# separately with: python3 parfleche.py
set -euo pipefail
cd "$(dirname "$0")"

if ! command -v python3 >/dev/null 2>&1; then
    echo "install: python3 was not found on PATH. Install Python 3.8+ first (see INSTALL.md)." >&2
    exit 1
fi

python3 - <<'PY'
import sys
if sys.version_info < (3, 8):
    sys.exit("install: Parfleche needs Python 3.8 or newer, found %s" % sys.version.split()[0])
print("install: python %s" % sys.version.split()[0])
PY

if python3 -m pip --version >/dev/null 2>&1; then
    if python3 -m pip install --upgrade pip setuptools wheel >/dev/null 2>&1; then
        echo "install: pip tooling refreshed"
    else
        echo "install: could not reach PyPI to refresh pip tooling (offline) - continuing, Parfleche has no dependencies"
    fi
else
    echo "install: pip is not available - continuing, Parfleche has no dependencies"
fi

# Loud self-check: a broken single file fails here, not at first boot.
python3 -c "import parfleche; assert parfleche.SCHEMA_VERSION == 1"
echo "install: parfleche.py imports cleanly ($(python3 -c 'import parfleche; print("v" + parfleche.__version__)'))"

if python3 -m pytest --version >/dev/null 2>&1; then
    echo "install: pytest available - run the suite with: python3 -m pytest -q"
else
    echo "install: pytest not installed - the suite also runs with: python3 -m unittest discover -s tests -v"
fi

echo "install: done. Start the shell with: python3 parfleche.py (or run ./demo.sh)"
