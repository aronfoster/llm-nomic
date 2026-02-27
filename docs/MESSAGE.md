# Message Structure and Prompt Caching

This document explains how LLM messages are constructed in the engine, why
the system + user split matters for prompt caching, and the failure mode that
led to the current design.

---

## How Messages Are Built

Each player turn is driven by a series of API calls (propose → revise →
vote → memory_update for the proposer; begin_discussion + discuss for
discussers). Two builder methods produce the initial message pair that
anchors each session:

- `PromptBuilder.build_proposer_system_message()` — returns
  `tuple[ChatMessage, ChatMessage]`
- `PromptBuilder.build_discusser_system_message()` — returns
  `tuple[ChatMessage, ChatMessage]`

Both return a `(system_message, user_message)` tuple. The caller unpacks
the pair and passes it to `LLMPlayer._reset_history()`, which initialises
`turn_history` with `[system, user]`.

### What goes in each message

**System message** — stable context that does not change across the calls
within a session:

| Block | Content |
|-------|---------|
| Persona | Player name + personality text (`PERSONA`, `STRATEGIC_GUIDANCE`) |
| Game state | Scores, move number, turn order, leaderboard context |
| Rules | Full current rule list |
| Memory | Player's private memory (omitted when empty) |

**User message** — phase-specific instruction that varies per call:

| Phase | User message content |
|-------|----------------------|
| propose | `INSTRUCTION_PROPOSE` (JSON schema, examples) |
| discuss | Proposal block + `INSTRUCTION_DISCUSS` |
| revise | Discussion summaries + `INSTRUCTION_REVISE` (appended in subsequent call) |
| vote | Vote instruction (appended in subsequent call) |
| memory_update | Memory update prompt (appended in subsequent call) |

For the second call onward in a session, the phase instruction is **appended**
to the growing `turn_history` as an additional user message. The initial
`[system, user]` pair is never replaced — it anchors the cache prefix.

---

## Why This Helps Caching

Both Anthropic and xAI use **prefix-based prompt caching**: a cached entry is
reused when the beginning of a new request exactly matches the beginning of a
previously cached request.

### The invariant that makes caching work

```
Every API call in a session sends:

  system: [persona + game_state + rules + memory]   ← byte-identical every time
  messages: [
    {role: "user",      content: INSTRUCTION_PROPOSE},    ← call 1 onward
    {role: "assistant", content: <proposal>},             ← call 2 onward
    {role: "user",      content: <discussions + REVISE>}, ← call 3 onward
    ...
  ]
```

Because the system block is byte-identical on every call, the provider can
return a cache hit on calls 2, 3, and 4. Only the first call in a session
incurs cache-write cost.

### Anthropic

Anthropic's caching is explicit. `AnthropicApiClient` sends
`cache_control: {"type": "ephemeral"}` on every call. The cache is keyed
on the full prefix up to the marked block. When the system content is
identical, Anthropic returns `cache_read_input_tokens > 0` from call 2
onward and charges at the reduced cache-read rate (~10% of full price).

### xAI

xAI's caching is automatic prefix matching. No explicit parameter is needed.
The cache key is derived from the prefix of the message list. When the system
message is identical, xAI reports `cached_tokens` in the usage object.

---

## The Failure Mode This Replaces

Before the fix, both builder methods returned a single
`ChatMessage(role="system")`, and `_reset_history()` set
`turn_history = [system_message]`.

**Call 1 (propose):** `turn_history` contained only a system message. The
Anthropic client requires at least one user message. When none was present, it
fell back to promoting the entire system content to a user message and
clearing `system_prompt`:

```python
# Old demotion fallback (removed)
if not anthropic_messages and system_prompt:
    anthropic_messages = [{"role": "user", "content": system_prompt}]
    system_prompt = None
```

This produced:

```
# Call 1 (propose) — BEFORE fix
system: null
messages: [{role: "user", content: EVERYTHING}]

# Call 2 (revise) — BEFORE fix
system: EVERYTHING
messages: [{role: "assistant", ...}, {role: "user", ...}]
```

Zero shared prefix → complete cache miss on every first→second transition.
For xAI the same structural mismatch (`[system]` alone vs.
`[system, assistant, user]`) broke automatic prefix matching.

The token log evidence from `CACHE_BUG.md`:

| Phase | cache_write | cache_read | Expected |
|-------|-------------|------------|----------|
| propose | 5,159 | 0 | — (cold) |
| **revise** | **6,361** | **0** | **~5,159** |
| vote | 0 | 6,361 | ✓ |
| memory_update | 0 | 7,215 | ✓ |

Revise was re-writing the entire system prompt from scratch instead of reading
it from cache.

---

## Token Savings

For a typical proposer session (~5,000 system tokens):

| | propose | revise | vote | memory_update |
|-|---------|--------|------|---------------|
| Before | write 5K | **write 5K** | read 5K | read 6K |
| After  | write 5K | read 5K | read 5K | read 6K |

At 3 players × ~10 moves, that is approximately **150,000 tokens saved per
game**, plus the price differential between cache-write and cache-read rates.

---

## Implementation Reference

| File | Role |
|------|------|
| `src/nomic_engine/llm/prompt_builder.py` | `build_proposer_system_message()` and `build_discusser_system_message()` — return `(system, user)` tuples |
| `src/nomic_engine/players/llm_player.py` | `_reset_history(system, user)` — initialises `turn_history = [system, user]`; `propose()` and `begin_discussion_turn()` unpack the tuple |
| `src/nomic_engine/llm/api_clients.py` | `AnthropicApiClient` — sends `cache_control: {"type": "ephemeral"}` on every call; demotion fallback removed |
| `src/nomic_engine/utils/token_usage_logger.py` | Logs `cache_creation_tokens` and `cache_read_tokens` per call to `token_usage.jsonl` |

---

## LLMJudge Caching (Sprint 36, Task 3 + Amendment)

`LLMJudge` applies the same stateful-history pattern to its four per-turn
calls, enabling cache hits from the second call onward within a turn.
The amendment moved the expensive turn context (rules, proposal, votes,
scores) from the first user message into the system message, so the entire
stable context is part of the cached prefix.

### The `_turn_history` pattern

`LLMJudge` maintains `_turn_history: list[ChatMessage]` that grows across
`get_veto → assess_scores → maintain_state → update_memory`:

```
After get_veto succeeds:
  _turn_history = [
    {role: "system",    content: JUDGE_SYSTEM_PROMPT
                                 + rules + proposal + votes + scores
                                 [+ memory]},                    ← cached
    {role: "user",      content: JUDGE_VETO_TEMPLATE},
    {role: "assistant", content: <veto JSON>},
  ]

After assess_scores appends:
  _turn_history = [
    ...same three messages as above...
    {role: "user",      content: JUDGE_SCORE_TEMPLATE},
    {role: "assistant", content: <score JSON>},
  ]

After maintain_state appends:
  _turn_history = [
    ...same five messages as above...
    {role: "user",      content: JUDGE_MAINTAIN_STATE_TEMPLATE},
    {role: "assistant", content: <state JSON>},
  ]

update_memory sends:
  _turn_history + [{role: "user", content: MEMORY_UPDATE_PROMPT}]
```

### Wire format per call

| Call | System (cached) | Messages |
|------|-----------------|----------|
| `get_veto` | persona + rules + proposal + votes + scores [+ memory] | `[veto_instruction]` |
| `assess_scores` | ← byte-identical, cache hit | `[…, veto_assistant, score_instruction]` |
| `maintain_state` | ← byte-identical, cache hit | `[…, score_assistant, maintain_instruction]` |
| `update_memory` | ← byte-identical, cache hit | `[…, maintain_assistant, memory_instruction]` |

### Why the system message is byte-identical on every call

`get_veto` calls `_build_judge_system_message(rules, game_state, proposal,
votes, discussions, memory_content)` once and stores the result as
`_turn_history[0]`. Every subsequent call within the same turn sends exactly
this same `ChatMessage` object. Anthropic therefore returns
`cache_read_input_tokens > 0` on calls 2, 3, and 4 without a new cache-write.

### Context in the system message (amendment)

`_build_judge_system_message()` calls
`PromptBuilder.build_judge_context_block(rules, game_state, proposal, votes,
discussions)` which returns the context as a plain string. This string is
concatenated with `JUDGE_SYSTEM_PROMPT` (and optionally the memory block)
to form the system message. The old `build_judge_context_message()` (which
returned a `ChatMessage` for a separate user message) is removed, along with
the unused `build_judge_score_context_message()`.

### assess_scores: no re-send of ruleset

No context-building call is made by `assess_scores`. The full ruleset,
proposal, votes, and discussion context are already present in
`_turn_history[0]` (the system message) from `get_veto`. Only
`build_judge_score_prompt` (the scoring instruction) is appended. This
removes a duplicate context block from every scoring API call.

### update_memory: cache hit, no cache-write charge

`update_memory` appends only the memory prompt and sends
`_turn_history + [memory_prompt]`. The system message at `_turn_history[0]`
is byte-identical to what was cached by `get_veto`. Anthropic returns a
cache hit — no cache-write charge on the memory step.

### Turn reset

`GameLoop._reset_judge_turn_state()` clears both `_judge_turn_responses` and
`_turn_history` at the start of each turn. `get_veto` (always the first judge
call per turn) then re-initialises `_turn_history` fresh with the current
turn's system message (which includes the full context for that turn).

### `_judge_turn_responses` still populated

`_judge_turn_responses` continues to accumulate the assistant-role responses
from all three calling methods. `GameLoop._update_all_memories()` reads this
list and passes it to `LLMPlayer.update_memory()` calls so players can see
the judge's reasoning when writing their own memories.

### Implementation Reference

| File | Role |
|------|------|
| `src/nomic_engine/judge/llm_judge.py` | `_turn_history` accumulator; `get_veto` builds system message with full context and initialises `[system, veto_prompt]`; `assess_scores` and `maintain_state` append prompts and responses; `update_memory` sends it |
| `src/nomic_engine/llm/prompt_builder.py` | `build_judge_context_block()` — returns context as a plain string for embedding in the system message |
| `src/nomic_engine/core/game_loop.py` | `_reset_judge_turn_state()` — clears both `_judge_turn_responses` and `_turn_history` |
| `tests/src/nomic_engine/judge/test_llm_judge.py` | Unit tests for `_turn_history` initialisation, accumulation, retry growth, and message structure |
| `tests/src/nomic_engine/test_persistent_memory_update.py` | Integration tests for turn reset, `update_memory` message structure, and `_judge_turn_responses` accumulation |
