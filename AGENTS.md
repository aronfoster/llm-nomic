# AGENTS Instructions

These rules apply to every AI coding agent working in this repository
(Claude Code, Codex, and similar tools).

---

## Environment and setup

- **Python version:** 3.12
- **Install dependencies:** `make install` (runs `pip install -r requirements.txt` and
  `pre-commit install`)
- **Key dependencies:** pydantic, pyyaml, openai, anthropic, google-genai,
  python-json-logger, python-dotenv
- **Dev tooling:** pytest, mypy (strict), black (line-length=79), ruff

### Common make targets

| Command | What it does |
|---------|--------------|
| `make ci` | Full quality gate — lint + typecheck + test. **Run before every commit.** |
| `make format` | Auto-format with black and ruff --fix |
| `make lint` | Check-only lint (no changes) |
| `make typecheck` | mypy over `src/` |
| `make test` | pytest over `tests/` |

`make ci` is the single command that must pass before pushing. It runs all three
checks in sequence and prints `✓ All quality checks passed!` on success.

Tests require `PYTHONPATH=.:src` (already set by the Makefile targets).

---

## Git hooks

Pre-commit hooks are configured in `.pre-commit-config.yaml` and installed by
`make install`. They run automatically on every `git commit`:

- **black** — reformats Python files under `src/` and `tests/` (line-length 79)
- **ruff** — lints and auto-fixes Python files under `src/` and `tests/`

The hooks are **fast formatters only** — mypy and pytest are intentionally
excluded from pre-commit (they run in `make ci` instead).

If pre-commit is not yet installed (e.g. a fresh clone), run `make install` once
to activate the hooks. After that, `git commit` will auto-format and auto-fix
before the commit is recorded. If hooks modify files, the commit is aborted so
you can stage the changes and re-commit — this is normal behaviour.

---

## `# noqa` and other check bypasses — strict policy

Bypassing lint, type, test, or security rules is **prohibited** unless there
is no practical way to structure the code correctly.

### What counts as a bypass

- `# noqa` (ruff/flake8)
- `# type: ignore` (mypy)
- `pragma: no cover` (coverage)
- `per-file-ignores` additions in `pyproject.toml`
- Any other mechanism that silences a tool without fixing the underlying issue

### Before reaching for a bypass, always try the correct fix first

Most common lint rules have a proper structural fix:

| Rule | Wrong | Right |
|------|-------|-------|
| FBT001/FBT002 — boolean positional/default arg | `def f(flag: bool = False) # noqa` | Use `count=True` (int) for CLI flags; use an enum or separate functions elsewhere |
| ANN* — missing annotation | `# noqa: ANN201` | Add the annotation |
| SLF001 — private member access | `# noqa: SLF001` | Expose a public method or use the public API |
| ERA001 — commented-out code | `# noqa: ERA001` | Delete the dead code |

### When a bypass is genuinely unavoidable

Unavoidable means: the rule fires on code that is **correct by design** and
**cannot be restructured** to satisfy the rule without making the code worse
(e.g. an untyped third-party boundary, a required stdlib pattern the rule
doesn't understand).

If that threshold is met:

1. Keep the bypass as narrow as possible — single line, single code, never
   a file-wide or project-wide suppression.
2. Write an inline comment **immediately above or on the same line** that
   explains:
   - exactly why the rule fires
   - exactly why the code cannot be restructured to avoid it
   - what would need to change in the future to remove the bypass
3. Mention the bypass and its rationale in the PR description.

**Example of an acceptable bypass:**

```python
# ANN401: `response` is typed as `Any` because the Plaid SDK's
# TransactionsResponse does not expose typed field accessors; every
# field access goes through __getattr__ which returns Any. This will
# be removable if/when plaid-python ships a typed model layer.
response: Any = client.transactions_sync(body)  # noqa: ANN401
```

**Example of an unacceptable bypass:**

```python
def doctor(verbose: bool = False) -> None:  # noqa: FBT002
```

This is wrong because FBT002 has a correct structural fix (use `count=True`
and `int` instead of `bool`), so the noqa comment is not justified.

---

## Sprint tracking

When you complete a task from `SPRINT.md`, mark it done in that file before
committing.  Add `DONE ✅` to the start of the task's heading line, for example:

```
### DONE ✅ Task 3: Plaid webhook signature verification
```

This keeps the sprint board accurate for the next developer (human or agent)
picking up the next task.

---

## Required behavior summary

1. Run the full quality gate before committing, including `make ci`.
2. Fix the root cause of failures; do not suppress them.
3. If a bypass is truly unavoidable, follow the narrow-bypass + detailed
   comment policy above.
4. Include quality-gate output in your task summary.
5. Mark completed tasks in `SPRINT.md` (see **Sprint tracking** above).
6. Ensure `ROADMAP.md` reflects the completed changes.
