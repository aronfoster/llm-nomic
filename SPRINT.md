# Sprint 38 — Better Loops

**Goal(s):**
- Need to have all LLM input failures (e.g. bad rule number, ABSTAIN vote when not allowed, etc.) go through retry logic with basic (sanitized) error descriptions so the LLM can fix it.
- This should be a smart refactor that creates reusable components appropriately, and leaves the codebase easier to understand
- Secondary Goals - if sprint has room, fix bugs:
  - Need to change text on last withdrawal attempt to make it clear that withdrawing is still an option, just skips your turn
  - Remove ephemeral block from memory_update for Anthropic clients so we're not paying to write to the cache.

---

## Tasks

<!--
  Instructions for the PM:
  - Copy the task block below for each task in the sprint.
  - Fill in Title, Priority, Description, and Acceptance Criteria.
  - Leave Notes blank or remove the section if there is nothing to add.
  - Acceptance Criteria should be concrete and testable so the Developer
    can check them off one by one.
  - Keep each task small enough to land as a standalone PR with make ci passing.
-->

### Task 1 — <Title>

**Priority:** High / Medium / Low

**Description:**
<What needs to be done and why. Focus on the desired outcome, not how to
implement it. Include relevant background context the Developer would not
already know.>

**Acceptance Criteria:**
- [ ] <Specific, testable criterion>
- [ ] <Specific, testable criterion>
- [ ] Tests added or updated to cover the new behavior
- [ ] `make ci` passes

**Notes:**
<Optional: links to related issues, constraints, edge cases to watch for,
or anything that does not fit neatly into the criteria above.>

---

### Task 2 — <Title>

**Priority:** High / Medium / Low

**Description:**
<What needs to be done and why.>

**Acceptance Criteria:**
- [ ] <Specific, testable criterion>
- [ ] <Specific, testable criterion>
- [ ] Tests added or updated to cover the new behavior
- [ ] `make ci` passes

**Notes:**
<Optional context.>

---

<!-- Add additional Task blocks as needed. -->
