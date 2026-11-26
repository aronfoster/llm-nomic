# **Project Plan: Nomic LLM Engine**

> **Active sprint tasks are tracked in [SPRINT.md](./SPRINT.md).**
> This file tracks the long-term backlog, bug lists, and future work.

This document tracks the high-level plan for the `llm-nomic` project.

## Near-term delivery roadmap: real games and correctness

The immediate objective is a repeatable development loop: run inexpensive
subscription-backed games in GrokBot and ChatGPT Dot virtual computers,
save them to Google Drive, review correctness, and fix demonstrated engine
and prompt defects. No new competitive features are needed for this loop.

### How the daily team should use this roadmap

- Chief of Staff coordinates and maintains the existing YouTrack queue;
  PM/planner turns the next ready packet below into small LN issues with
  acceptance criteria; engineer implements; independent reviewer checks
  and merges under the current [team decisions](https://foster.youtrack.cloud/articles/LN-A-1).
  Preserve the existing roles and review gates.
- Each pass: read current LN issues, active claims and exact GitHub PR
  metadata; reconcile completed work and outstanding review findings.
  Do not create duplicate tickets or repeat already accepted work.
- Keep at least one independent offline packet ready when live sign-in,
  provider access, or another PR blocks progress. Continue ready work in
  dependency order; do not wait for the entire milestone to finish.
- Put active specifications in YouTrack and use SPRINT.md for sprint
  tracking. Keep this roadmap current as packets are accepted. Record
  blockers, next actor, evidence and the next actionable packet in the
  existing coordination process. Escalate genuine owner decisions only;
  no new scheduling service or coordination mechanism is required.
- Code changes require offline regression tests, make ci, independent
  review and the existing merge gates. Never run live inference in CI.

### P0 — Finish subscription-backed execution (existing LN-1)

**Status:** container setup, bounded API game support (LN-5), and offline
test isolation (LN-7) are implemented. Live subscription acceptance is
not established. Existing work takes precedence over new provider work.

- [LN-2](https://foster.youtrack.cloud/issue/LN-2): prove supported provider
  and host readiness; identify official authentication/invocation,
  subscription eligibility, available inexpensive models, tool isolation,
  usage reporting and host/session persistence. Do not assume an OAuth
  token is an API key or that a consumer login authorizes arbitrary
  endpoints.
- [LN-4](https://foster.youtrack.cloud/issue/LN-4) and
  [LN-14](https://foster.youtrack.cloud/issue/LN-14): finish xAI CLI adapter
  and bounded live-run preparation; resolve existing review findings
  including LN-10/11. [LN-3](https://foster.youtrack.cloud/issue/LN-3):
  finish OpenAI subscription provider preparation. Coordinate the shared
  live-run entry point across these workstreams; do not duplicate it.
- [LN-6](https://foster.youtrack.cloud/issue/LN-6): verify the existing
  host/provider acceptance matrix, recording actual supported combinations
  and blockers. Both GrokBot and at least one ChatGPT Dot must be able to
  operate independently using an eligible existing subscription; preserve
  the wider matrix in LN-6 and escalate unsupported combinations rather
  than quietly weakening acceptance.
- Before any live run, demonstrate an offline fake-provider full game
  through the real adapter, clean dry-run, bounded retries and timeouts,
  isolated credentials and tools, distinct game directories, logging,
  usage accounting, and clean refusal on auth/quota/network failures.
  Preserve existing API-key modes without silently falling back to them.
- Obtain owner authorization for live sign-in and any separately billed
  inference. Prefer one-time official login with supported refresh;
  never extract another application's credentials or use undocumented
  endpoints. Record reauthentication requirements honestly.
- Acceptance: a bounded real game on each required host, restart behavior,
  actual model and provider, subscription billing mode, completed turns,
  stop reason and sanitized per-turn/per-game usage evidence in LN.
  Missing usage is unavailable, not zero; retain existing fail-closed
  behavior. A fake run or models-list response is not live acceptance.

### P1 — Portable game records (start offline in parallel with P0)

**P1a — Archive contract and local export/import.** PM can schedule now.
Reuse the existing game instance directory as the authoritative data;
do not create a second game-state database.

- Export a uniquely identified, versioned snapshot of a game directory,
  including config, game_state.json, rules.jsonl, rules.md, transcript,
  structured game log, token_usage.jsonl, and any game-local memory,
  snapshots or other files needed for review and resume. Include a
  manifest with game ID, engine commit/version, ruleset, provider/model
  identifiers, personalities, effective non-secret settings, timestamps,
  completed turn/checkpoint, status and stop reason, file inventory and
  checksums. Preserve effective prompts or references plus exact
  revision sufficient to reconstruct them.
- Export completed, capped, failed and interrupted games. Make a
  consistent snapshot at a safe boundary; distinguish a resumable
  checkpoint from a diagnostic-only partial turn. Never imply a
  mid-turn state is safe to resume unless verified.
- Exclude credentials, environment files, provider homes, auth headers
  and tokens, unrelated files and sensitive diagnostic material. Use
  an explicit file selection and sanitized output; do not publish runtime
  game records to the public source repo. Record missing evidence rather
  than inventing it. Validate archive paths and integrity before import;
  no path traversal, symlink escapes or overwrite of an existing game.
- Acceptance: synthetic game export/import round-trip into a fresh
  directory preserves authoritative state and resumes at a verified
  checkpoint using fakes; negative tests cover secret canaries,
  corruption, collision and incomplete games. Reviewers can inspect
  the archive without executing its contents or invoking a model.
  Document the format and reproducible commands.

**P1b — Google Drive handoff.** Depends on P1a; investigate authorized
Drive access on both hosts in parallel. Use an owner-controlled private
Drive location for game archives, not a public link or source repo.
Start with a simple supported upload/download workflow; automate only
where necessary for unattended daily runs. No new storage service.

- Give each snapshot a stable game ID and distinct revision; preserve
  originals, avoid duplicate uploads on retry, verify readback/checksum,
  and retain the local archive if upload fails.
- Acceptance: GrokBot exports a synthetic game, uploads it, and a Dot
  independently downloads and verifies/imports it (and vice versa).
  Record Drive file links/IDs and checksums in the relevant LN issue,
  not credentials. If a host lacks authorized access, record that
  blocker and retain local export capability.

### P2 — Inexpensive sample games

Depends on P0 for the selected host/provider and P1a for local capture;
P1b enables unattended cross-host review. Do not delay a locally
archivable authorized smoke game solely because Drive upload is pending.

- First use the existing cheap profile as a starting point (two players,
  one LLM judge, three turns; 60 calls, 150000 tokens, 1200 seconds per
  process, 60-second call timeout, 2048 output tokens). Select an
  actually supported inexpensive subscription model, adjusting the profile
  only as needed for its contract. Record exact limits and any differences.
  The token cap is approximate; preserve documented overshoot and
  restart semantics. No uncapped or separately billed runs without
  authorization.
- Run one short game per ready host, archive every outcome, and review
  before escalating length. Then run a small set of roughly 5–10-turn
  games, with varied personalities or proposals where useful to exercise
  rule changes, scoring and participant information. Increase length
  only when previous evidence is usable and budgets permit. Do not
  require games to reach victory; capped games are valuable.
- Acceptance: at least one genuine archived game from each required host,
  followed by several reviewable sample games. Each record identifies
  the exact engine revision, models, limits, usage and outcome. Stop
  repetitive live runs when a reproducible defect blocks meaningful play;
  route it to the fix queue instead.

### P3 — Correctness review of every sample game

PM may develop the review checklist and synthetic review fixtures in
parallel with P0/P1. Actual game review depends on recorded evidence.
Review against the rules and information in force at the specific turn,
not the final ruleset. Focus on four categories:

1. **Judge correctness:** Was the judge's ruling consistent with the
   applicable rules, timing, votes, precedence and available facts?
   Distinguish ambiguous rules from clear errors.
2. **Missing engine automation:** Did an enacted rule introduce behavior
   that the engine should be able to perform automatically but did not?
   Example: award every player points equal to the turn count at the
   specified phase. Determine the intended timing, recipients, amount
   and recurrence; identify the missing engine capability. Do not
   prohibit legitimate game-breaking rule changes merely because the
   engine cannot yet automate them.
3. **Scoring correctness:** Independently calculate expected point
   awards/deductions, recipients, timing, totals and victory consequences
   from applicable rules and events. Distinguish wrong judge output
   from wrong application of correct output, missing automation, or
   incorrect persisted state.
4. **Participant information:** Did a player or judge lack information
   a human in that role would reasonably know (e.g. turn order, current
   proposer, public rules, scores, prior rulings or relevant public
   history)? Inspect the actual effective input, not merely the final
   transcript. Do not reveal information a participant should not know.

For every finding record game/archive ID, engine revision, turn and
phase, rule IDs and applicable text, evidence pointers, expected versus
actual behavior, impact, suspected component and proposed next action.
Mark uncertainty and missing evidence explicitly; do not infer hidden
reasoning. Review artifacts are separate from authoritative game state.
An unusual but valid strategic move is not itself a defect.

**P3a — Evidence sufficiency:** verify a reviewer can reconstruct rules,
scores and turn order at each relevant step and inspect the public
information supplied to each participant, using existing logs first.
If necessary add minimal structured events/snapshots and sanitized
prompt-input records; test them offline. No hidden chain-of-thought
capture is required.

**P3b — Review workflow:** establish a repeatable Markdown review
template/checklist with the four categories and a sample reviewed
synthetic archive. Store reviews separately alongside the game in Drive
and reference actionable findings in LN. Independent review is useful
for disputed rulings; avoid duplicate tickets.

### P4 — Gameplay-driven fixes and regression loop

- Triage concrete findings into existing or new LN issues. Prioritize
  incorrect rulings, corrupted state or scores, missing executable rule
  behavior and missing participant context over speculative features.
  Group duplicate manifestations by root cause, while retaining game
  evidence. Existing LN-8/9/13 and other open work remain in the queue
  with their existing dependencies and containment.
- For each fix, reproduce the smallest relevant game state and recorded
  model output offline; add regression tests that fail before the fix
  and pass afterward. Separate deterministic engine/scoring tests from
  judge/prompt-input contract tests. A mocked response alone does not
  establish improved live judge judgment; check that on a later bounded
  game. Do not rewrite prior game archives or silently change historical
  scores.
- For enacted automation, design bounded, validated engine behavior
  that applies at the correct phase and exactly once, survives resume,
  and preserves rule authority. Test the demonstrated rule, relevant
  negative cases and timing/recipient boundaries. Do not execute
  arbitrary model-generated code or grant access to host tools.
- Run offline CI and independent review; then use the next authorized
  short game to confirm practical behavior and discover the next set of
  issues. Compare against earlier archives; keep unresolved findings
  visible. This is a recurring loop, not a one-time milestone.

### Scheduling and completion

P0 is already staffed; P1a and P3 planning/fixtures are the next
independent offline packets. P1b access discovery can proceed without
credentials being copied or new permissions being granted. P2 begins
as soon as an eligible route and local capture are ready. P3/P4 repeat
after each run. The PM should keep enough small, non-overlapping tickets
ready for daily work and use actual gameplay evidence to select further
engine improvements. Defer speculative UI, dynamic game structure and
other long-term features unless a review finding justifies them.

## LN-1 container readiness

Container bootstrap and quality checks: done
([Container readiness](docs/CONTAINERS.md)). SOCKS proxy support is included
without changing the container proxy settings. Subscription sign-in, capped
live games and milestone acceptance remain open in
[LN-1](https://foster.youtrack.cloud/issue/LN-1). This does not replace the
coordinator/planner roles or close the milestone.

## Core Principles

Our architecture is built on these principles:

1.  **Security, Structure First:** Code will be secure and clean (ala Uncle Bob)
2.  **Engine vs. Instance:** The Game Engine is stateless and operates on "Game Instance" directories.
3.  **Permit Play** The Game Engine should allow game-breaking behavior if the players vote on it and judge allows it.
4.  **Authoritative Data:** The Game Instance is the sole authority on game state. `rules.jsonl` and `game_state.json` are the sources of truth.
5.  **Stand alone PRs:** All PRs are small enough to understand, `make ci` passes, and contain unit tests that cover new code

## Bug List Game Engine

### HIGH PRIORITY

- None

### Low Priority

- Rules 107, 202, and 205 interaction: If players amend the base rules to allow newly-passed scoring rules to apply retroactively to the turn they were adopted (contrary to current interpretation), the judge scoring prompt would need updating to reflect this change. Currently the prompt explicitly instructs judges not to apply rule changes retroactively.


## Future Work

This is the long-term backlog and TODO scratchpad.

### Engine Features

* **Improve LLM API Efficiency**
  * Should remove json instruction and have per-provider json flags set for 4 big providers. Fallback to the instruction for Ollama + new providers.
  * Implement async behavior (per model provider?)
    * Batch processing for 24 hour turn around (game summary?). Unlikely to benefit for the near future.
  * Can we get the "thinking" from thinking llm models? Add that as a new field into the logs and transcript?
    * Apparently you just tell them to put it in `<thinking>` blocks. Anthropic lets you pass a parameter, too. Gemini needs a parameter set. OpenAI doesn't share. Open models usually respect the `<thinking>` prompt.
    * We will not include this because it conflicts with json flags.
  * Explore https://openrouter.ai/ support for tokens/models, along with other providers
  * Cache token usage tested on xAI and Anthropic. Need to test behavior with Google, OpenAI, and Ollama.
    * Ollama should correctly log tokens but not use caching
    * Google and OpenAI should log token usage and show significant caching.
    * Need to add a note somewhere about minimum 16k tokens, recommend 32k tokens as a model context requirement

* **Rate Limiting & Cost Tracking**
  * Per-turn and per-game usage reports, optional call/token/wall bounds, per-call timeouts, and `max_output_tokens` landed with LN-5. Reports are built from `token_usage.jsonl`. Unavailable usage is listed separately from zero. A token cap is not precise: one call can overshoot by up to `max_output_tokens` plus its prompt, and missing usage stops the next call.
  * Dollar cost per game is still open. It would need a price per million tokens, with optional per-game overrides.
  * Startup API-key checks are outside the game usage budget.
  * See README.md, "Inexpensive test games", for the cheap profile and `python -m src.nomic_engine.main --game_dir <dir> --turns 3`.
  
* **Game State & Rules**
  * Flag for whether to assess points after a withdrawal
  * Create more personalities: chaos monkey: tries to break the engine
  * Think more about the llm model picker
    * Should we allow custom model config per game (e.g., for new/local models not in `models.yml`)?
    * Shoudl we query provider APIs to get a list of available models?
  * Add the ability of the scoring judge to use random numbers, which would allow Suber's original rule 202 that used a D6 for scoring
    * Would be ideal to allow arbitary random ranges and math to enable creative scoring rules (e.g. 6 points plus a random 1-6 points)
  * Rule 113 asserts that players can quit. Right now we assume all players play forever. Should we remove this rule or add a way to quit the game? Need to track turns differently. Could be part of a more dynamic turn handling system.
  * Rule snapshots, memory snapshots, score snapshots for replays

* **Dynamic Game Structure**
  * Create "turn structure" game file that defines each step, and can be changed by the judge (maybe players, too, by consensus?). This allows extra steps to be created, or order of steps to be changed.
    * Therefore if rules change the turn steps (e.g an additional round of discussion after voting) it can be supported. Might need to ask the judge to define the steps and provide some guidance to the players.
  * Explore tool calling/MCP to allow players+judge to dynamically modify turn processing.
  * Update judge prompt to have it remind itself on future turns if game state must change.
  * Support for multiple votes per player

* **Game Loop: Looping**
  * ~~Explore running more than one turn on application execution~~ *(Sprint 39)*
  * ~~Improve console logging to only show game output, not INFO logging about engine steps~~ *(Sprint 39)*
  * ~~**Graceful soft-interrupt**: Detect a keypress (e.g., any non-Ctrl+C key) while a turn is running
    and finish the current turn cleanly before pausing, rather than hard-terminating. Requires
    background thread polling for input while the turn executes. Ctrl+C remains a hard interrupt.~~ *(Sprint 40)*
  * ~~**Full interactive CLI app**: Replace the current "one invocation =
    one turn" model with a single long-running process that is the primary way to play.
    The operator launches the CLI once and is presented with a menu to continue an existing
    game or create a new one. The selected game then runs turn-by-turn with no manual
    re-launch. When a game ends (or the operator quits), the menu returns. The CLI should
    never require the operator to pass `--game_dir` flags or know about internal file paths.~~ *(Sprint 40)*

### Visualization (Web app)

* Deferred: consider a read-only game viewer only if actual correctness reviews demonstrate that the existing transcript and structured archive are insufficient.

### Graphical UI

* Have a GUI for running the game in Electron (?)

### Development

* ~~Offline unit tests: importing the engine does not load `.env`. The
  suite drops provider credentials and, inside the pytest process,
  blocks synchronous TCP connects, non-loopback DNS lookups
  (`getaddrinfo` / `gethostbyname`), and non-loopback UDP `sendto`.
  A subprocess can still open its own sockets. `main()` loads `.env`
  after arguments are accepted; `--help` does not.~~ *(LN-7)*
* Improve code documentation using markdown files for developers (especially Claude Code and Codex) to read
