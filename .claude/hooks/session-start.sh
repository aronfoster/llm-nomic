#!/bin/bash
set -euo pipefail

if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

cd "${CLAUDE_PROJECT_DIR:-.}"

while IFS= read -r line; do
  # skip comments and empty lines
  [[ "$line" =~ ^[[:space:]]*# ]] && continue
  [[ -z "${line// }" ]] && continue

  pip install "$line" --break-system-packages --quiet \
    || echo "WARNING: could not install '$line', skipping"
done < requirements.txt