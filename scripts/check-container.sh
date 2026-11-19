#!/usr/bin/env bash
# Bootstrap a clean Python container and run the existing quality gate.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."
python3 -c 'import sys; assert sys.version_info[:2] == (3, 12), "Python 3.12 is required"'
python3 -m venv venv
# `python3 -m venv` keeps an existing bin/python symlink. A venv built with
# another Python would otherwise be used for pip and the quality gate.
if ! venv/bin/python -c 'import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 12) else 1)'; then
    echo "error: venv/bin/python is not Python 3.12. Remove the existing venv/ directory and run this script again." >&2
    venv/bin/python -V >&2 || true
    exit 1
fi
venv/bin/python -m pip install --disable-pip-version-check -r requirements.txt
export PATH="$PWD/venv/bin:$PATH"
make ci
