# Container readiness

Use a container with Python 3.12 (including `venv`), Bash, Git and Make.
Docker is not required inside an already-running container.

From a fresh checkout, run:

```sh
bash scripts/check-container.sh
```

The script works from any current directory. It installs the pinned direct
requirements into the ignored `venv/` directory, then runs the existing
`make ci` quality gate. Dependency installation requires package-index network
access. SOCKS proxy support is included for provider SDK initialization;
the script preserves the container proxy settings. Transitive requirements are not locked. It does not modify global
Python packages, install Git hooks, create credentials, authenticate to
providers, or start a live game. Use `make install` inside the activated
virtual environment if you also need the repository's commit hooks.

For later commands in the same checkout:

```sh
source venv/bin/activate
make ci
python -m src.nomic_engine.main --help
```

## Remaining milestone work

Passing the quality gate establishes software/test readiness, not subscription
authentication or a successful live game. OpenAI and xAI currently use API-key
clients in `src/nomic_engine/llm/api_clients.py`; a subscription token is not a
drop-in replacement for those keys. Do not copy credentials from another app
or call undocumented endpoints. Provider integration remains separate LN-1
work, subject to the official provider flow and eligibility requirements.

Do not run paid API games as a substitute for subscription acceptance. The
milestone also requires a cheap game profile, a usage cap, per-turn/game usage
reporting and independent review before Aron merges. `--turns` bounds turns
only, not token usage or spending. Never add local credentials or game output
to this public repository.
