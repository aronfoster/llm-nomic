# LN-4 grok CLI contract proof

Offline process-adapter prototype for `grok -p --output-format json`.
The adapter is not on the default game path. Zero-tool isolation is
**not established**. The adapter stays behind the named gate
`acknowledge_unverified_tool_isolation`.

## CLI version

Official installer, stable channel, linux-x86_64:

```bash
curl -fsSL https://x.ai/cli/install.sh | bash
```

Installed into a throwaway `HOME`. No login. No `-p` prompt. No API key.

`grok --version` and `grok version` both printed:

```text
grok 1.0.89 (28be5bb1bf65)
```

Help was read with `grok --help`, `grok -h`, and `grok help` (the help
text says to use `grok help` for the longer form). Subcommand help was
read only for `grok help mcp`, `grok help plugin`, `grok help agent`,
and `grok help memory`. None of those commands send a prompt.

## Help excerpts relied on

From `grok help` for 1.0.89:

```text
--always-approve
    Auto-approve all tool executions
--disable-web-search
    Disable web search and web fetch tools
--disallowed-tools <TOOLS>
    Built-in tools to remove (comma-separated)
--max-turns <N>
    Maximum number of agent turns
--no-alt-screen
    Run inline instead of using the terminal alternate screen
--no-plan
    Disable plan mode
--no-subagents
    Disable subagent spawning
--output-format <OUTPUT_FORMAT>
    Output format for headless mode
    possible values: plain, json, streaming-json, streaming-messages-json
-p, --single <PROMPT>
    Single-turn prompt. Prints the response to stdout and exits
--permission-mode <MODE>
    possible values: default, acceptEdits, auto, dontAsk,
    bypassPermissions, plan
--tools <TOOLS>
    Built-in tools to allow (comma-separated)
--cwd <CWD>
    Working directory
```

`--deny` is described as a permission allow/deny rule, with compat alias
`--disallowedTools`. That is a different flag from `--disallowed-tools`.
Neither removes every tool.

`grok help mcp` lists `enable` and `disable` for one configured server.
`grok help plugin` lists `enable` and `disable` for one plugin by name.
`grok help agent` includes:

```text
--plugin-dir <DIR>
    Load a plugin from this directory for this process only (repeatable).
    Highest-priority plugin scope; always trusted: hooks and MCP servers
    activate without a prompt.
--always-approve
    Auto-approve all tool executions
```

There is no `--no-hooks`, `--no-plugins`, `--no-mcp`, or
`--no-project-instructions` flag in this help.

`docs.x.ai` currently also lists `--no-memory` and `--no-auto-update`.
Those two flags are **not** in the 1.0.89 help that was inspected, so
the adapter does not pass them. The headless scripting page documents
`GROK_DISABLE_AUTOUPDATER=1` for scripts. The settings reference
documents `GROK_HOME` (default `~/.grok`), `GROK_SUBAGENTS`,
`GROK_MEMORY`, `GROK_WEB_FETCH`, `GROK_WRITE_FILE`, and the
`GROK_CURSOR_*` / `GROK_CLAUDE_*` compatibility scanners (default on).

The upstream headless guide (grok-build `14-headless-mode.md`, not the
installed `--help`) says `--tools` keeps MCP meta-tools available. The
installed help does not say that an empty `--tools` value means no
tools. This adapter does not pass `--tools` or `--disallowed-tools`.

## Verified contract

Proven with a local Python fake CLI. The real `grok` binary is not
executed by tests.

- Opt-in only. `select_grok_cli_adapter` requires `enabled=True` and
  `acknowledge_unverified_tool_isolation=True`. Either flag false raises
  `GrokCliAdapterDisabled` and does not spawn.
- `create_api_client` refuses `provider="grok_cli"` with that gate name.
  It does not read an API key and it does not spawn a process. Existing
  provider branches are unchanged.
- The child is started with `start_new_session=True`. On timeout or
  cancel the adapter sends `SIGTERM` to the process group, waits, then
  sends `SIGKILL`, then reaps the direct child.
- Stdout and stderr are capped. Crossing a cap kills the group and
  raises `GrokCliTruncatedOutputError`.
- `--output-format json` is required in the argv the adapter builds.
  One JSON object is parsed. `text` must be a string on success.
- Missing usage, non-object usage, boolean token counts, and
  `usage_is_incomplete: true` stay `usage_available=False` with both
  token counts `None`. Integer zero stays zero and available. Counts
  are never coerced to zero. This matches LN-5.
- Auth, quota, and network wording on a CLI error object (or on stderr
  when stdout is empty) map to `GrokCliAuthError`, `GrokCliQuotaError`,
  and `GrokCliNetworkError`. Malformed JSON on exit 0 is
  `GrokCliMalformedOutputError`. A non-zero exit that is not one of
  those is `GrokCliNonZeroExitError`. `stopReason` `max_tokens` is
  truncated. `stopReason` `cancelled` is cancelled.
- No paid HTTP client is invoked from this module. The child
  environment is an allowlist: synthetic `HOME` and `GROK_HOME`, no
  parent environment, no provider API keys, no real `~/.grok` auth
  cache. A git working directory is refused.
- The argv does not include `--always-approve`, `--yolo`,
  `--dangerously-skip-permissions`, `bypassPermissions`, `--tools`,
  `--disallowed-tools`, `--max-turns`, `--plugin-dir`, or `--allow`.
  A caller who puts `--always-approve` in the executable prefix is
  refused before spawn.
- Partial flags that **are** passed, because help describes them, and
  that are **not** a zero-tool proof: `--no-alt-screen`, `--no-plan`,
  `--no-subagents`, `--disable-web-search`, plus `--cwd` pointed at the
  disposable directory and `--output-format json`.

The timeout test's fake ignores death-on-`SIGTERM` (it records the
signal and keeps sleeping) and forks a descendant in the same process
group that does the same. After the adapter returns, both PID files
show `SIGTERM` was delivered and neither PID remains in `/proc`.

## Unsupported or unverified

**Zero-tool isolation is gated, not established.**

What was not found, offline, as a guarantee that a headless turn has
no tools:

| Surface | What 1.0.89 help and the docs actually say |
| --- | --- |
| Built-in tools | `--tools` is an allowlist of built-in tools. `--disallowed-tools` removes a comma-separated list. Empty `--tools` is not documented as none. A finite denylist is not every tool. |
| MCP | `grok mcp disable` takes one server name and edits config. Help does not show a session flag that disables MCP. The upstream headless guide says MCP meta-tools survive `--tools`. |
| Hooks and plugins | No disable-all flag. `plugin disable` is per name. `--plugin-dir` loads plugins and says their hooks and MCP servers activate without a prompt. The adapter never passes `--plugin-dir`. |
| Web | `--disable-web-search` says it disables web search and web fetch tools. That was not executed, so inline server-side web search is unverified. |
| Subagents | `--no-subagents` says it disables subagent spawning. Not executed. |
| Project instructions | No flag says project rules, `CLAUDE.md`, or `.grok` instructions are ignored. `--system-prompt-override` replaces the agent system prompt; help does not say it drops project instructions. An empty temp cwd and a synthetic `HOME` / `GROK_HOME` are containment, not a documented off switch. |
| Compat scanners | Settings docs default the Cursor/Claude scanners to on. The child env sets those variables to `0`. Help does not mention them. This is not proof they are off, and it does not cover grok-native hooks, plugins, or tools. |
| Read-only | `--sandbox` and `GROK_WRITE_FILE=0` are not "no tools". The adapter does not pass `--sandbox`. `GROK_WRITE_FILE=0` is only the write tool. |

**LN-5 enforcement is not claimed.** `--max-turns` is "Maximum number
of agent turns". The headless docs say that counter is main-agent
rounds that reported usage, that subagent sampler calls do not increase
it, and that it is not an exact match for `--max-turns` when rounds
lack usage. Inference `max_retries` is a separate setting. An agent-turn
cap is not a bound on internal model requests or retries. The adapter
does not pass `--max-turns`.

## Remaining live-only checks

These need a real `grok` process. They were not run. This note does not
treat them as done.

- Whether the argv above still advertises built-in tools, MCP
  meta-tools, hooks, plugins, skills, or project instructions on a real
  turn.
- Whether `--disable-web-search` also suppresses inline server-side web
  search.
- Whether a synthetic `HOME` and `GROK_HOME` actually stop the binary
  from reading a user auth cache, plugins, and hooks.
- The real process's auth, quota, and network error strings. The typed
  mapping uses the documented `{"type":"error","message":...}` object
  plus conservative markers. It is not a capture from 1.0.89.
- The real `--output-format json` usage object, including when
  `usage_is_incomplete` is set and when cost fields are omitted.
- That a timeout against the real CLI reaps descendants that leave the
  process group (`setsid`, a leader daemon, a double fork). The fake
  descendant stays in the group.
- Any claim that CLI retries or `--max-turns` satisfy LN-5.

## Smallest next step

One authenticated live probe, still without `--always-approve`,
`--yolo`, or `bypassPermissions`. Run the adapter's argv with
`--output-format streaming-messages-json` only long enough to read the
`system` / `init` line (`tools`, `mcp_servers`, `skills`) and then kill
the process group. If that list is not empty, or if help still has no
flag that clears it, keep `acknowledge_unverified_tool_isolation` in
place. Do not treat that probe as an LN-5 budget.
