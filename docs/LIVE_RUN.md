# First bounded game on a subscription sign-in (grok CLI)

This is the one-command path for LN-6. It uses the official `grok` CLI
signed in with an xAI subscription, not an API key. Nothing here reads
`.env` or `XAI_API_KEY`, and there is no paid API fallback.

## What it is, and what is not proven

- Each model call is one `grok --output-format json -p <prompt>` process
  run by the adapter from LN-4 (`grok_cli_adapter.py`).
- The CLI is an agent. Its isolation from tools, MCP servers, hooks and
  plugins is **not proven** for grok 1.0.89 (see
  `docs/evidence/ln4-grok-cli-contract.md`). The adapter narrows it
  (`--no-subagents`, `--disable-web-search`, `--no-plan`, empty temp
  working directory, allowlisted environment, dedicated home) but does
  not establish zero tools. A live run therefore needs the explicit
  `--acknowledge-unverified-tool-isolation` flag.
- Whether the CLI reports `usage.input_tokens` / `usage.output_tokens`
  in its JSON is unverified. If it does not, the token cap stops the run
  after the first call (safe). See "If usage is missing" below.

## Steps

1. Preview, with no side effects:

   ```sh
   python -m src.nomic_engine.live_run grok-cli --dry-run
   ```

2. Sign in once, on the computer that will run the game. The sign-in
   goes in a dedicated directory, never `~` or `~/.grok`. The dry run
   prints the exact command. It looks like:

   ```sh
   HOME=$HOME/.nomic-grok-home GROK_HOME=$HOME/.nomic-grok-home/.grok \
     /absolute/path/to/grok login --device-auth
   ```

   Open the printed code URL, approve it with the xAI account, wait for
   success. Credentials stay in that directory (mode 0700 or stricter).

3. Run the bounded game:

   ```sh
   python -m src.nomic_engine.live_run grok-cli \
     --acknowledge-unverified-tool-isolation
   ```

## Bounds (defaults)

Two players plus an LLM judge, 2 turns, at most 40 model calls
(retries count), at most 200,000 known tokens, 1,200 seconds in total,
120 seconds per call. The usage guard checks before every call and the
run stops with exit code 3 and a usage report. Tune with `--turns`,
`--max-calls`, `--max-tokens`, `--max-wall-seconds`,
`--call-timeout-seconds`.

## If usage is missing

If the run stops after one call because usage is unavailable, the CLI
did not report token counts. Re-run with `--allow-missing-usage`. That
drops the token cap, so the call and time caps are the only bounds.
Record this in LN-6 as evidence.

## Stopping and cleanup

Ctrl-C stops the game and the CLI process group. Remove the sign-in
with `HOME=... GROK_HOME=... grok logout` and delete the dedicated home.
