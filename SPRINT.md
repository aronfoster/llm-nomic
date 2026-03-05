# Sprint 38 — Better Loops

**Goal(s):**
- Need to have all LLM input failures (e.g. bad rule number, ABSTAIN vote when not allowed, etc.) go through retry logic with basic (sanitized) error descriptions so the LLM can fix it.
- This should be a smart refactor that creates reusable components appropriately, and leaves the codebase easier to understand
- Secondary Goals - if sprint has room, fix bugs:
  - Need to change text on last withdrawal attempt to make it clear that withdrawing is still an option, just skips your turn
  - Remove ephemeral block from memory_update for Anthropic clients so we're not paying to write to the cache.

---

## Background

The existing retry pattern covers JSON-parse failures. When an LLM returns malformed JSON
or a response that fails schema validation, the engine appends the bad response and an error
message to the conversation history and asks the LLM to try again. This pattern is
duplicated identically in seven places across `LLMPlayer` (propose, discuss, revise, vote)
and `LLMJudge` (veto, score, maintain_state).

Two classes of failure are **not** covered today:

1. **Illegal proposals** — A proposal passes JSON parsing (valid structure, valid rule type)
   but fails game-legality validation (e.g., AMEND targeting a rule ID that doesn't exist).
   The engine currently logs the illegal proposal and ends the turn with no retry.

2. **ABSTAIN-when-forbidden** — A player votes ABSTAIN when the `allow_abstention` flag is
   False. The engine currently raises a `ValueError` immediately with no retry.

The sprint fixes both gaps and refactors the duplicate retry code into a shared component.

---

## Tasks

### Task 1 — Extract shared retry helper

**Priority:** High

**Description:**
The retry loop for JSON-parse failures is copy-pasted in seven places across `LLMPlayer`
and `LLMJudge`. Each copy has the same shape: loop up to N attempts, call the API, try to
parse, on `ValueError` append the bad response + error message to conversation history and
continue, on success return the result, on exhaustion fall back or raise.

Extract this pattern into a single shared helper so the duplication is gone and future
changes to retry behavior only need to happen in one place. This task also makes three
small, targeted behavior improvements while touching these call sites (see Intentional
Behavior Changes below).

#### The Seven Locations

| Action | File | Approx. Lines | Max-retries config key | Fallback on exhaustion |
|--------|------|---------------|------------------------|------------------------|
| `propose` | `players/llm_player.py` | 150–281 | `tuning.max_propose_retries` | raise `RuntimeError` |
| `discuss` | `players/llm_player.py` | 316–416 | `tuning.max_discuss_retries` | return empty `Discussion` (abstain) |
| `vote` | `players/llm_player.py` | 418–535 | `tuning.max_vote_retries` | return `Vote(vote="ABSTAIN")` |
| `revise` | `players/llm_player.py` | 585–709 | `tuning.max_revise_retries` | return original proposal (KEEP) |
| `get_veto` | `judge/llm_judge.py` | 172–288 | `tuning.max_judge_veto_retries` | raise `RuntimeError` |
| `assess_scores` | `judge/llm_judge.py` | 290–413 | `tuning.max_judge_score_retries` | raise `RuntimeError` |
| `maintain_state` | `judge/llm_judge.py` | 415–540 | `tuning.max_judge_maintain_state_retries` | raise `RuntimeError` |

#### Common Loop Shape (All 7 Copies)

Every loop:

1. Iterates `for attempt in range(max_retries)`
2. Calls `self.api_client.get_completion(history)` and extracts `result.text`
3. On `response_text is None` (API error): logs and `continue`s to next attempt
4. Calls the action-specific parse function inside a `try` block
5. On parse success: appends the response as an `assistant` `ChatMessage` to the
   conversation history, then returns the result
6. On `ValueError`: logs the error; if this was the last attempt, `break`s; otherwise
   appends the bad response as `assistant` + a retry `user` message, then continues
7. After the loop: executes the action-specific fallback (return or raise)

#### Per-Action Differences the Helper Must Preserve

**Retry message templates** (all defined in `llm/prompts.py`):

| Action | Template constant |
|--------|------------------|
| `propose` | `PROPOSE_RETRY_TEMPLATE` |
| `discuss` | `DISCUSS_RETRY_TEMPLATE` |
| `vote` | `VOTE_RETRY_TEMPLATE` |
| `revise` | `REVISE_RETRY_TEMPLATE` |
| `get_veto` | `JUDGE_VETO_RETRY_TEMPLATE` |
| `assess_scores` | `JUDGE_SCORE_RETRY_TEMPLATE` |
| `maintain_state` | `JUDGE_MAINTAIN_STATE_RETRY_TEMPLATE` |

All seven templates must include a `{validation_error}` placeholder. Currently
`DISCUSS_RETRY_TEMPLATE` and `VOTE_RETRY_TEMPLATE` do not — update them to match the
others. The helper always formats the template with `str(e)` from the caught `ValueError`.

**LLMJudge-specific: secondary response tracking.**
On a successful parse, the three `LLMJudge` actions also append the assistant message to
`self._judge_turn_responses` (a separate list used later by `update_memory()`). Only the
final response for each action (veto, score, maintain_state; successful or unsuccessful) should appear in
this list — retried or rejected responses must never be added to it. The helper
must support an optional secondary-append parameter for this; the `LLMPlayer` actions do
not use it.

**UX print statement (standardized for all actions).**
Every LLM call — player and judge alike — must print a status message before the API call
is made. Currently only `LLMPlayer` actions do this. The helper should accept a short
action description string (e.g., `"thinking about a proposal"`, `"deciding on a veto"`)
and print a consistent message using it. Exact wording is left to the Developer, but the
format should be uniform and work for both player and judge contexts.

**Conversation history variable name (standardize in this task).**
`LLMPlayer` stores its history in `self.turn_history`; `LLMJudge` stores it in
`self._turn_history`. Standardize both to `turn_history`. The rename is small and natural
here because the helper already abstracts away the variable name (history is passed as a
parameter). The helper itself does not care about the name — this is purely cleanup at the
class level.

**`_log_usage` call.**
Each loop calls `self._log_usage(result, "<action_name>")` immediately after getting the
completion. This is a one-liner per call site and is fine to keep at each call site rather
than inside the helper, as the action label differs each time.

#### Intentional Behavior Changes

These three behaviors change deliberately as part of this task:

1. **Retry error context for `discuss` and `vote`**: After this task, retry prompts for
   `discuss` and `vote` will include the specific validation error (matching all other
   actions). Previously they sent a generic message with no error detail.

2. **Judge UX print statements**: `LLMJudge` actions will now print a status message
   before each LLM call, the same as `LLMPlayer` actions. Previously judge calls were
   silent.

3. **History variable name**: `LLMJudge._turn_history` will be renamed to
   `LLMJudge.turn_history`, matching `LLMPlayer`. No runtime behavior change.

#### What Must Not Change

Everything else must behave identically:

- The number of LLM calls made for any sequence of parse outcomes
- The exact sequence of `ChatMessage` objects appended to conversation history on both
  success and failure paths (aside from the retry-message content change for `discuss`/`vote`)
- The exact object returned (or exception raised) on success, on each specific exhaustion
  fallback, and on repeated API-error (`None`) responses
- Log output at `warning` and `error` levels (level and approximate message content)
- `_judge_turn_responses` contains only the single successful assistant message per action,
  never retried responses

#### Testing

- Add direct unit tests for the helper that exercise: (a) success on first attempt,
  (b) failure then success (retry path), (c) exhaustion with raise, (d) exhaustion with
  graceful fallback return, (e) `None` API response handling (skip and continue)
- Update or fix any existing tests that break due to the refactor
- Remove tests that no longer reflect current structure

**Acceptance Criteria:**
- [x] The retry loop is no longer duplicated across `LLMPlayer` and `LLMJudge`
- [x] All seven retry templates include `{validation_error}` and the helper always formats with it
- [x] A status print message is emitted before every LLM call (player and judge)
- [x] `LLMJudge._turn_history` renamed to `LLMJudge.turn_history`
- [x] `_judge_turn_responses` never contains retried/rejected responses
- [x] Tests added or updated to cover the retry helper directly
- [x] `make ci` passes

**Notes:**
This is the natural foundation for Tasks 2 and 3, but those tasks may proceed before or
after this one at the Developer's discretion.

---

### Task 2 — Retry on illegal proposals

**Priority:** High

**Description:**
When a player's proposal passes JSON parsing but fails game-legality validation, the engine
currently ends the turn with no retry. This task wires legality failures into the same retry
loop used for JSON-parse failures, so the LLM gets a chance to correct the mistake.

The same fix applies to the revision phase: a MODIFY action that produces an illegal revised
proposal currently ends the turn silently (treated as withdrawal); it should also retry.

#### Current Behavior (the bugs being fixed)

**Proposal step (`_get_and_validate_proposal` in `core/game_loop.py`):**
After `propose()` returns, the game loop assigns `proposal_id`, calls `validate_proposal()`,
and — if the proposal is illegal — logs it, clears `proposal_id`, and returns `None`. The
turn ends immediately. The player is never told what was wrong; there is no retry.

**Revision step (`_handle_revision` in `core/game_loop.py`):**
After `revise()` returns a new proposal object (MODIFY action), the game loop re-validates
it. If illegal, it logs the error and returns `None`. This is treated identically to a
withdrawal — the turn ends with no vote, even though the original proposal was valid. There
is no retry.

#### Required New Behavior

**Proposal legality retry:**
- When a structurally-valid proposal fails `validate_proposal()`, inject the error message
  into the player's conversation history and prompt the player to try again.
- Retry attempts for legality failures count against the same per-turn limit as JSON-parse
  failures: the combined total of all proposal attempts (parse failures + legality failures)
  must not exceed `tuning.max_propose_retries`.
- On exhaustion: raise `RuntimeError` (same as today — the turn ends).

**Revision legality retry:**
- When a MODIFY action produces an illegal revised proposal, inject the error message into
  conversation history and prompt the player to try another revision (another
  KEEP/MODIFY/WITHDRAW response).
- Retry attempts count against `tuning.max_revise_retries`, shared with JSON-parse
  failures in the revision phase.
- On exhaustion: **fall back to KEEP** — return the original `proposal` unchanged and
  proceed to the vote. Do **not** return `None`; the original proposal was valid and the
  game should continue with it.
  - This differs from the current behavior, which returns `None` (withdrawal).

#### Retry Prompt Templates

Add two new constants to `llm/prompts.py`:

- `PROPOSE_LEGALITY_RETRY_TEMPLATE` — used when a proposal passes JSON parsing but fails
  legality validation.
- `REVISE_LEGALITY_RETRY_TEMPLATE` — used when a MODIFY revision passes JSON parsing but
  fails legality validation.

Both templates must follow a **generic format**: `{validation_error}` carries the full
explanation of what went wrong (e.g., `"Rule 999 not found."` or `"Cannot amend immutable
rule 101."`). The template body itself should **not** re-embed action-specific rules or
the full JSON schema — the error message is self-explanatory. A short reminder of the
expected output format (key names only, no rules) is acceptable and left to the Developer.
Both templates must contain a `{validation_error}` placeholder.

The existing `PROPOSE_RETRY_TEMPLATE` and `REVISE_RETRY_TEMPLATE` (used for JSON-parse
failures) are unchanged.

#### Wiring Legality Validation into the Retry Loop

Legality validation must happen **inside** the retry loop so that its failures consume
attempts from the same counter as JSON-parse failures. The Developer has full discretion
over the implementation approach (e.g., a `post_parse_validator` parameter on
`llm_retry_loop()`, a validator-wrapping closure passed as `parse_fn`, or another
pattern). The constraint is purely behavioral: one shared attempt counter, one unified
retry loop.

**`proposal_id` handling:** `validate_proposal()` requires a non-`None` `proposal_id`.
The game loop currently assigns this from `game_state.next_proposal_id` after `propose()`
returns. If legality validation is pulled into the `propose()` retry loop, the Developer
must ensure the correct ID is assigned before validation and that the proposal returned by
`propose()` still has `proposal_id=None` (the game loop's post-return check at
`_get_and_validate_proposal` line 402 enforces this).

**Double-validation:** After this task, legality validation will happen inside the retry
loop before `propose()` returns. The existing call to `validate_proposal()` in
`_get_and_validate_proposal()` will be redundant for the normal path. The Developer should
clean this up to avoid redundant work; keeping it as a defensive assertion is acceptable
if the Developer prefers.

#### Files to Be Aware Of

| File | Relevance |
|------|-----------|
| `src/nomic_engine/players/llm_player.py` | `propose()` (lines 151–235) and `revise()` (lines 448–525) — primary change sites |
| `src/nomic_engine/core/game_loop.py` | `_get_and_validate_proposal()` (lines 363–430) and `_handle_revision()` (lines 544–610) — existing legality-check logic |
| `src/nomic_engine/validation/validator.py` | `validate_proposal(proposal, player_name, game_manager) -> tuple[bool, str]` |
| `src/nomic_engine/llm/retry_helper.py` | `llm_retry_loop()` — the shared helper from Task 1; may need extension |
| `src/nomic_engine/llm/prompts.py` | Add `PROPOSE_LEGALITY_RETRY_TEMPLATE`, `REVISE_LEGALITY_RETRY_TEMPLATE` |
| `src/nomic_engine/data_models.py` | `Proposal` dataclass; `GameState.next_proposal_id` |

#### Legality Error Messages (for reference)

`validate_proposal()` returns these error strings on failure:

| Scenario | Error string |
|----------|-------------|
| Proposer name mismatch | `"Player {player_name} submitted an illegal proposal attributed to {proposal.proposer_name}."` |
| ADD with target_rule_id | `"Add proposals must not have a target_rule_id."` |
| ADD without new_text | `"Add proposals must have new_text."` |
| ADD where rule ID already exists | `"Rule {proposal_id} already exists."` |
| AMEND without target_rule_id | `"Amend proposals must have a target_rule_id."` |
| AMEND without new_text | `"Amend proposals must have new_text."` |
| AMEND targeting non-existent rule | `"Rule {target_rule_id} not found."` |
| AMEND targeting immutable rule | `"Cannot amend immutable rule {target_rule_id}."` |
| REPEAL without target_rule_id | `"Repeal proposals must have a target_rule_id."` |
| REPEAL targeting non-existent rule | `"Rule {target_rule_id} not found."` |
| REPEAL targeting immutable rule | `"Cannot repeal immutable rule {target_rule_id}."` |
| TRANSMUTE without target_rule_id | `"Transmute proposals must have a target_rule_id."` |
| TRANSMUTE targeting non-existent rule | `"Rule {target_rule_id} not found."` |

#### Other Similar Gaps

The Developer should search for any other location where a structurally-valid LLM response
is accepted by the parser but subsequently rejected for game-state reasons, and apply the
same pattern. The two known cases are illegal proposals and illegal revised proposals.

**Acceptance Criteria:**
- [ ] An illegal proposal (bad rule ID, immutable target, etc.) causes a retry with the
  legality error message injected into conversation history
- [ ] An illegal revised proposal (MODIFY action) causes a retry, not a silent withdrawal
- [ ] Combined JSON-parse + legality attempt count is bounded by `max_propose_retries`
  (proposal) and `max_revise_retries` (revision) respectively
- [ ] On proposal exhaustion: `RuntimeError` raised (turn ends, same as today)
- [ ] On revision exhaustion: original proposal returned unchanged (KEEP); turn proceeds
  to vote — **not** treated as withdrawal
- [ ] `PROPOSE_LEGALITY_RETRY_TEMPLATE` and `REVISE_LEGALITY_RETRY_TEMPLATE` added to
  `llm/prompts.py`; both contain `{validation_error}`; neither embeds game rules in the
  template body
- [ ] Tests added or updated to cover: proposal legality retry (succeeds on retry),
  proposal legality exhaustion (RuntimeError), revision legality retry (succeeds on retry),
  revision legality exhaustion (KEEP fallback), combined parse+legality attempt counting
- [ ] `test_run_turn_stops_on_illegal_proposal` and
  `test_step_3_revise_rejects_illegal_revised_proposal` updated to reflect new retry
  behavior (these currently test that failures end the turn immediately)
- [ ] `make ci` passes

---

### Task 3 — Retry on ABSTAIN-when-forbidden

**Priority:** High

**Description:**
When `allow_abstention` is False and an LLM player votes ABSTAIN, the engine should send
the player an error message explaining that ABSTAIN is not permitted and ask them to vote
YES or NO. Retry attempts count against the same `max_vote_retries` limit.

If all retries are exhausted and the player still votes ABSTAIN, the engine should record
a NO vote as the fallback (not crash or raise).

**Acceptance Criteria:**
- [ ] An ABSTAIN vote when `allow_abstention=False` triggers a retry with a clear error
  message injected into conversation history
- [ ] After retries are exhausted, the vote is recorded as NO
- [ ] The total vote attempt count is bounded by the existing `max_vote_retries` limit
- [ ] No `ValueError` is raised by the vote collection path for this case
- [ ] Tests added or updated to cover the retry and fallback paths
- [ ] `make ci` passes

---

### Task 4 — Fix withdrawal last-attempt text (if sprint has room)

**Priority:** Low

**Description:**
On the final withdrawal retry attempt, the prompt sent to the LLM implies that withdrawing
is not an option. It should instead make clear that withdrawing is still possible, but
doing so will skip the player's turn entirely.

**Acceptance Criteria:**
- [ ] On the last withdrawal attempt, the prompt text communicates that withdrawal is
  still available but results in a skipped turn
- [ ] Tests updated to reflect the new prompt text
- [ ] `make ci` passes

---

### Task 5 — Remove ephemeral block from memory_update (if sprint has room)

**Priority:** Low

**Description:**
The `memory_update` call for Anthropic clients sends an ephemeral cache block, which
incurs unnecessary cache-write charges. The system message is already cached from the
earlier `get_veto` call, so the ephemeral block is redundant. Remove it so Anthropic
clients benefit from the cache hit without paying to write again.

**Acceptance Criteria:**
- [ ] The `memory_update` call for Anthropic clients no longer sends an ephemeral block
- [ ] Cache hit behavior is preserved for the system message prefix
- [ ] Tests updated or added to cover the change
- [ ] `make ci` passes

---

<!-- Add additional Task blocks as needed. -->
