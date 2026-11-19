#!/usr/bin/env bash
# Bootstrap a clean Python container and run the existing quality gate.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."
python3 -c 'import sys; assert sys.version_info[:2] == (3, 12), "Python 3.12 is required"'
python3 -m venv venv
venv/bin/python -m pip install --disable-pip-version-check -r requirements.txt
export PATH="$PWD/venv/bin:$PATH"
make ci
