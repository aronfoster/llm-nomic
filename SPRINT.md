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
changes to retry behavior only need to happen in one place. The external behavior of all
seven actions must remain identical after the refactor.

**Acceptance Criteria:**
- [ ] The retry loop is no longer duplicated across `LLMPlayer` and `LLMJudge`
- [ ] All seven actions (propose, discuss, revise, vote, judge veto, judge score, judge
  maintain_state) behave identically to before the refactor
- [ ] Tests added or updated to cover the retry helper directly
- [ ] `make ci` passes

**Notes:**
This is a pure refactor — no behavior change. It is the natural foundation for Tasks 2 and
3, but those tasks may proceed before or after this one at the Developer's discretion.

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
