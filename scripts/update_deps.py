#!/usr/bin/env python3
"""
Fetch the latest available version of every package in requirements.txt
and rewrite the file with exact pins (package==X.Y.Z).

Run via:  python3 scripts/update_deps.py
Or via:   make update-deps  (also installs & runs make ci)

If the latest version of any package cannot be determined the original
line is kept unchanged and a warning is printed to stderr.
"""

import re
import subprocess
import sys
from pathlib import Path

REQ_FILE = Path(__file__).parent.parent / "requirements.txt"


def latest_version(package: str) -> str | None:
    result = subprocess.run(
        [sys.executable, "-m", "pip", "index", "versions", package],
        capture_output=True,
        text=True,
    )
    match = re.search(r"\(([^)]+)\)", result.stdout)
    return match.group(1).strip() if match else None


def main() -> None:
    lines = REQ_FILE.read_text().splitlines(keepends=True)
    updated: list[str] = []
    errors = False

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            updated.append(line)
            continue

        pkg = re.split(r"[=><!@\[]", stripped)[0].strip()
        version = latest_version(pkg)
        if version:
            updated.append(f"{pkg}=={version}\n")
            print(f"  {pkg}: {version}")
        else:
            updated.append(line)
            print(
                f"  WARNING: could not determine latest version for {pkg}",
                file=sys.stderr,
            )
            errors = True

    REQ_FILE.write_text("".join(updated))
    print(f"\nrequirements.txt updated.")

    if errors:
        print(
            "\nWARNING: some packages could not be resolved (see above).",
            file=sys.stderr,
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
