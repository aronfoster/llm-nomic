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
- [ ] The retry loop is no longer duplicated across `LLMPlayer` and `LLMJudge`
- [ ] All seven retry templates include `{validation_error}` and the helper always formats with it
- [ ] A status print message is emitted before every LLM call (player and judge)
- [ ] `LLMJudge._turn_history` renamed to `LLMJudge.turn_history`
- [ ] `_judge_turn_responses` never contains retried/rejected responses
- [ ] Tests added or updated to cover the retry helper directly
- [ ] `make ci` passes

**Notes:**
This is the natural foundation for Tasks 2 and 3, but those tasks may proceed before or
after this one at the Developer's discretion.

---

### Task 2 — Retry on illegal proposals

**Priority:** High

**Description:**
When a player's proposal passes JSON parsing but fails game-legality validation (e.g.,
AMEND/REPEAL/TRANSMUTE targeting a rule ID that does not exist), the engine should feed the
error back to the LLM and retry rather than ending the turn. The error message sent to the
LLM must describe the specific legality violation.

Retry attempts for legality failures count against the same limit as JSON-parse failures
(i.e., the total number of propose attempts is bounded by the existing
`max_propose_retries`). If all retries are exhausted, the turn ends the same way it does
today.

The same fix applies to the revision phase: if a MODIFY action produces an illegal revised
proposal, that legality failure should also trigger a retry rather than silently treating
the revision as a withdrawal.

**Acceptance Criteria:**
- [ ] An illegal proposal (bad rule ID, etc.) causes a retry with the legality error
  message injected into conversation history
- [ ] An illegal revised proposal (from the revision phase) causes a retry with the
  legality error message, rather than silently withdrawing
- [ ] The total propose/revise attempt count is bounded by the existing retry limits
- [ ] On exhaustion, turn behavior matches the current fallback (turn ends)
- [ ] Tests added or updated to cover both the proposal and revision retry paths
- [ ] `make ci` passes

**Notes:**
The Developer should also look for any other similar gaps (valid JSON, failed legality) and
apply the same pattern. The known cases are illegal proposals and illegal revised proposals;
there may be others.

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
