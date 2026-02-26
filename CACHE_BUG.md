## 🐛 BUG: Prompt Caching Ineffective for Intra-Turn Calls (propose → revise → vote → memory_update)

**Status:** Open  
**Priority:** Medium (cost/performance, not correctness)  
**Affected providers:** Anthropic (confirmed), xAI / OpenAI / Google (partial — see notes per provider)

---

### Symptom

Within a single player turn, the `propose` call pays full input token cost, and the `revise` call also pays full input token cost despite containing nearly identical context. Cache hits only appear on `vote` and `memory_update` because those calls happen to share the system prompt prefix. The `revise` step, which has the most to gain from caching, gets nothing.

From the logs (Move 10, Claude/Sonnet):

| Call | Cache Write | Cache Read |
|---|---|---|
| propose | 5,159 | 0 |
| revise | 6,361 | 0 ← **should be hitting cache** |
| vote | 854 | 6,361 ✓ |
| memory_update | 784 | 7,215 ✓ |

---

### Root Cause

Two compounding problems:

**1. Incompatible message array structure between calls.**

`propose` sends a single `user` message containing the full context + proposal prompt. `revise` sends an `assistant` message (the prior proposal response) followed by a new `user` message (discussions + revision prompt). These two arrays share zero common prefix — not even the first token — so cache lookup fails entirely for `revise`.

**2. `cache_control` is placed at the top-level API payload, not inside a content block.**

```python
# WRONG — cache_control at top level has ambiguous/provider-specific behavior
{
  "model": "...",
  "messages": [...],
  "cache_control": {"type": "ephemeral"}   # ← this is the bug
}

# RIGHT — cache_control as a content block property on stable content
{
  "model": "...",
  "system": [
    {
      "type": "text",
      "text": "...stable context: game state, rules, memory...",
      "cache_control": {"type": "ephemeral"}   # ← pinned to the stable prefix
    }
  ],
  "messages": [...]
}
```

The incidental cache hits on `vote` and `memory_update` are happening because the SDK happens to apply the marker to the system prompt, which those calls share. `propose` and `revise` have different system prompts (one is bare, one includes the prior response), so the prefix diverges.

---

### The Fix

**Architectural principle:** Separate *stable* context (system prompt, game rules, player memory) from *dynamic* context (call-specific instructions, discussion history, prior responses). Cache the stable prefix. Pass dynamic content as the message tail.

#### Anthropic

Move all stable, turn-invariant content into the `system` array as a content block with `cache_control`:

```python
{
  "system": [
    {
      "type": "text",
      "text": build_stable_context(game_state, rules, memory),
      "cache_control": {"type": "ephemeral"}
    }
  ],
  "messages": [
    # propose:
    {"role": "user", "content": propose_prompt()},

    # revise (extend same array):
    {"role": "user", "content": propose_prompt()},
    {"role": "assistant", "content": prior_proposal_json},
    {"role": "user", "content": discussion_and_revise_prompt()},

    # vote (extend further):
    # ... etc.
  ]
}
```

All four intra-turn calls now share the same cached system prefix. Write once, read 3x.

#### xAI (Grok)

xAI does not charge for cache writes and uses implicit caching (no `cache_control` annotation needed). However, the same message structure problem applies — if the message array prefix diverges between calls, the provider's internal cache cannot reuse the KV state. Apply the same stable-prefix architecture. Verify cache behavior via the `cache_read_tokens` field in responses.

#### OpenAI

OpenAI uses automatic prompt caching (no explicit markers). Caching applies to the **longest common prefix** of the messages array. Same fix applies: keep stable content at the front of the messages array (or in the system message), and append dynamic content at the tail. The system message is always a good anchor.

Reference: https://platform.openai.com/docs/guides/prompt-caching

#### Google (Gemini)

Gemini uses explicit **Context Caching** via a separate API call that creates a named cache object, then references it via `cached_content` in subsequent requests. This is more powerful but requires a different integration pattern:

1. On game start (or when rules/state change significantly), create a cache object via `POST /v1beta/cachedContents` containing the stable context.
2. Pass the `cached_content` name in each player API call.
3. Invalidate/recreate the cache when rules change (after a successful proposal).
4. Note: minimum cacheable size is 32,768 tokens — we need to only use it when we expect the cache to be larger than that

Reference: https://ai.google.dev/gemini-api/docs/caching

---

### Provider Comparison Matrix

| Provider | Cache Mechanism | Write Cost | Annotation Required | Min Cache Size | Notes |
|---|---|---|---|---|---|
| Anthropic | Explicit `cache_control` blocks | +25% over base | Yes | 1,024 tokens | 5-min TTL default; system prompt is ideal anchor |
| xAI | Implicit (automatic) | None | No | Unknown | Verify via `cache_read_tokens` in response |
| OpenAI | Implicit (automatic) | None | No | 1,024 tokens | Longest prefix match; GPT-4o+ only |
| Google | Explicit Context Cache API | Storage + creation fee | Yes (separate API call) | 32,768 tokens | Most powerful; requires cache lifecycle management |

---

### Acceptance Criteria

- [ ] `revise` call shows `cache_read_tokens > 0` for Anthropic
- [ ] Intra-turn cost for Anthropic drops by ~40-50% (write-once, read-3x on stable context)
- [ ] Provider adapter layer has a `build_system_context()` method that returns stable content separately from dynamic call instructions
- [ ] Cache creation is idempotent within a turn (no redundant writes)
- [ ] For Google: cache is invalidated and recreated after any successful proposal (rules changed)