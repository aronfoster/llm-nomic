# CACHE_BUG: Prompt Caching Misses on First→Second Call Within Player Turns

**Status:** Root-caused, fix designed  
**Affects:** All providers (Anthropic, xAI), all player turns  
**Impact:** ~30–40% of cacheable input tokens are re-read at full price every turn

---

## 1. Symptom

Within a single player turn, the engine makes 4 API calls in sequence: propose → revise → vote → memory_update. Each call reuses the same system message and appends to a growing conversation history.

Caching works correctly from the **second→third→fourth** calls. But the **first→second** transition always misses cache. This pattern is universal across providers, players, and turns.

### Token log evidence (Move 10, Claude via Anthropic)

| Phase         | cache_write | cache_read | Expected read |
|---------------|-------------|------------|---------------|
| propose       | 5,159       | 0          | — (cold)      |
| **revise**    | **6,361**   | **0**      | **~5,159**    |
| vote          | 0           | 6,361      | ✓             |
| memory_update | 0           | 7,215      | ✓             |

### Token log evidence (Move 9, Max via xAI)

| Phase         | cache_write | cache_read | Expected read |
|---------------|-------------|------------|---------------|
| propose       | —           | 159        | — (cold)      |
| **revise**    | **—**       | **128**    | **~4,154**    |
| vote          | —           | 5,184      | ✓             |
| memory_update | —           | 6,016      | ✓             |

The pattern is identical: first→second = cache miss, second→third→fourth = cache hit.

---

## 2. Root Cause

### The monolithic system message

Currently, `PromptBuilder.build_proposer_system_message()` (and `build_discusser_system_message()`) packs **everything** into a single `ChatMessage(role="system")`:

```
system: [persona + game_state + rules + memory + INSTRUCTION_PROPOSE]
```

When `llm_player._reset_history()` is called, `turn_history` starts as:

```python
self.turn_history = [system_message]  # single system-role ChatMessage
```

The first API call (`propose`) sends **only** this system message — no user or assistant messages.

### Anthropic: system-to-user demotion

`AnthropicApiClient.get_completion()` (api_clients.py:217–224) requires at least one user message. When the only message is system-role, it demotes the entire system content to a user message and sets `system_prompt = None`:

```python
# api_clients.py lines 217-224
if not anthropic_messages and system_prompt:
    anthropic_messages = [{"role": "user", "content": system_prompt}]
    system_prompt = None
```

This produces two completely different wire formats:

**propose (1st call):**
```
system: null
messages: [{role: "user", content: EVERYTHING}]
```

**revise (2nd call):** (now has assistant + user messages from propose round)
```
system: EVERYTHING
messages: [{role: "assistant", ...}, {role: "user", ...}]
```

Zero bytes of shared prefix → complete cache miss.

### xAI: same symptom, same structural cause

The OpenAI-compatible client doesn't do demotion, but xAI's automatic prefix caching shows the same miss pattern. When the first call sends `messages: [{role: "system", ...}]` alone and the second sends `[{role: "system", ...}, {role: "assistant", ...}, {role: "user", ...}]`, the prefix matcher fails to reuse the first call's cache entry.

---

## 3. Proposed Fix: Split System Message into System + User

### Principle

Every API call — including the very first — must send at least `[system, user]`. This means the content currently packed into one system message needs to be split into:

- **system message** — stable identity and context (cacheable prefix)
- **user message** — phase-specific instructions (varies per call)

### What goes where

**System message (stable across all phases within a turn):**
- Persona block (personality text)
- Game state block
- Rules block
- Memory injection

**User message (varies per phase):**
- `INSTRUCTION_PROPOSE` (with examples, JSON enforcement, validation rules)
- `INSTRUCTION_DISCUSS` (with proposal block, examples)
- `INSTRUCTION_REVISE` (with discussions, constraint message, examples)
- `INSTRUCTION_VOTE` (with proposal block, examples)
- `MEMORY_UPDATE_PROMPT`

### Changes required

#### A. `prompts.py` — no template changes needed

The existing templates (`INSTRUCTION_PROPOSE`, `INSTRUCTION_REVISE`, etc.) already serve as self-contained instruction blocks. They just need to be routed to a user message instead of appended to the system message.

#### B. `prompt_builder.py` — return (system, user) tuples

Each `build_*_system_message()` method currently returns a single `ChatMessage(role="system")`. Change to return a tuple of two messages:

```python
def build_proposer_system_message(self, ...) -> tuple[ChatMessage, ChatMessage]:
    # Stable context → system
    blocks = [persona_block, game_state_block, rules_block]
    if memory_content.strip():
        blocks.append(memory_block)
    system_content = "\n\n".join(blocks)

    # Phase instruction → user
    instruction_block = prompts.INSTRUCTION_PROPOSE.format(
        json_format_enforcement=prompts.JSON_FORMAT_ENFORCEMENT,
        personality_examples=self._build_propose_examples(personality),
    )

    return (
        ChatMessage(role="system", content=system_content),
        ChatMessage(role="user", content=instruction_block),
    )
```

Same pattern for `build_discusser_system_message()`. The proposal block and discussion block should go in the user message along with the instruction, since they vary by phase.

#### C. `llm_player.py` — initialize history with [system, user]

```python
def _reset_history(self, system_message: ChatMessage, user_message: ChatMessage) -> None:
    self.turn_history = [system_message, user_message]
```

Update `propose()`, `discuss()`, etc. to unpack the tuple from the builder:

```python
system_msg, user_msg = self.prompt_builder.build_proposer_system_message(...)
self._reset_history(system_msg, user_msg)
```

For subsequent phases (revise, vote, memory_update), the phase-specific user message is **appended** to `turn_history` as it already is — the key difference is that `turn_history` started with `[system, user]` instead of `[system]`.

#### D. `api_clients.py` — Anthropic demotion becomes dead code

With every call guaranteed to have at least one user message, the demotion fallback at lines 217–224 never triggers. It can be removed or left as a defensive guard.

### Wire format after fix

**propose (1st call):**
```
system: [persona + game_state + rules + memory]
messages: [{role: "user", content: INSTRUCTION_PROPOSE}]
```

**revise (2nd call):**
```
system: [persona + game_state + rules + memory]    ← identical prefix ✓
messages: [
  {role: "user", content: INSTRUCTION_PROPOSE},
  {role: "assistant", content: <propose response>},
  {role: "user", content: <discussions + INSTRUCTION_REVISE>}
]
```

The system block is byte-identical across all calls. Both Anthropic (explicit caching) and xAI (automatic prefix caching) will match on the shared system prefix starting from the first call.

---

## 4. Expected Savings

For a typical proposer turn (~5,000 system tokens):
- **Before:** propose writes 5K, revise writes 5K again = 10K written, 5K wasted
- **After:** propose writes 5K, revise reads 5K from cache = 5K written, 0 wasted

At 3 players × ~10 moves, that's ~150K tokens saved per game, plus the cost differential between cache-read and cache-write pricing.