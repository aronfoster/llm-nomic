# Sprint 39 — CLI Multi-Turn Game Loop

**Goal(s):**
- Replace the single-turn executor with a multi-turn CLI loop so a game can run from start to finish (or to a turn cap) in one command.
- Clean up console output so game narrative is not buried in engine INFO logs.
- Add provider-native JSON mode flags to reduce prompt token waste and improve JSON reliability for major providers.

---

## Background

Today `main()` runs exactly one turn and exits. To play a game you must invoke the command once per turn, which makes automated and interactive play tedious. The ROADMAP describes the desired end state: pick or create a game, run turns until a key press or game-over, and see only the game narrative on the console (not engine internals).

The JSON mode item addresses a parallel inefficiency: every prompt includes text instructions to return JSON even for providers (OpenAI, Google, xAI) that support a native JSON-enforcement flag, wasting tokens and relying on the model to follow prose instructions when a structured flag would be more reliable.

---

## Tasks

### Task 1 — Multi-turn game loop

**Priority:** High

**Description:**
Change `main()` so that after loading the game and instantiating players and judge (done once), it loops over `game_loop.run_turn()` until the game ends naturally or a user-supplied cap is hit.

#### CLI changes

- Add optional `--max_turns N` argument. When omitted, run until game over. When supplied, stop after N turns even if the game is not finished.
- Existing `--game_dir` and `--verbose` (from Task 2) arguments are unchanged.

#### Loop behavior

- Print a clear separator at the start of each turn (e.g., `=== Turn N ===`).
- On game over (target score reached): print the victory summary and exit 0 — same content as today's single-turn path.
- On `--max_turns` reached without game over: print a short notice (e.g., "Reached max turns limit. Game paused.") and exit 0.
- On `KeyboardInterrupt` (Ctrl+C): finish the current in-progress turn, print a short notice, then exit 0. Do not abort mid-turn — the game state must remain consistent.

#### Startup validation

`validate_startup()` runs once before the loop, not once per turn.

#### Logging

`setup_logging()` runs once. The log file accumulates entries across all turns in the same invocation.

#### Acceptance Criteria

- [ ] `--max_turns N` argument accepted; omitting it runs until game over
- [ ] Victory summary is printed and process exits 0 when target score is reached
- [ ] Ctrl+C finishes the current turn cleanly before exiting
- [ ] `--max_turns` cap exits cleanly with a notice when reached
- [ ] `startup_validation` and `setup_logging` each run once per invocation
- [ ] `make ci` passes

---

### Task 2 — Console output cleanup

**Priority:** High

**Description:**
Today the console handler is at INFO level, which mixes engine-internal messages ("Game loaded successfully", "Instantiated 3 player(s)", etc.) with the game narrative that comes from `print()` statements in the game loop. In a multi-turn run this creates a lot of noise.

#### Required changes

- Lower the default console log level from INFO to WARNING. Only warnings and errors appear on the console by default.
- Add a `--verbose` flag to `main()`. When passed, restore the console handler to INFO level (original behavior). Useful for debugging.
- No changes to the file (JSON) handler — it stays at DEBUG.
- No changes to the `print()` statements in the game loop; they continue to produce all game narrative output.

#### Acceptance Criteria

- [ ] Default console output shows only WARNING and above
- [ ] `--verbose` flag restores INFO-level console output
- [ ] Game narrative (`print()` statements) is unaffected in both modes
- [ ] `make ci` passes

---

### Task 3 — Provider-native JSON mode flags

**Priority:** Medium

**Description:**
LLM prompts currently include text instructions telling the model to return JSON (e.g., "Return only valid JSON using the standard proposal schema."). For providers that support a native JSON-enforcement flag, this prose instruction wastes tokens and is less reliable than the flag. This task adds a `json_mode` capability flag to the model configuration and switches the three supported API clients to use native JSON mode when available, removing the text instruction from those prompts.

#### Model configuration

Add a boolean `json_mode` field to `ModelDefinition` in `data_models.py` (default `False`). Set it to `True` in `models.yml` for models that support it (OpenAI, xAI, and Google providers). Anthropic is excluded — it already enforces structure via schema-based tool calling.

#### API client changes

Each client receives `json_mode` from the model config and activates the provider-native flag when `True`:

- **`OpenAICompatibleApiClient`** (OpenAI and xAI providers): pass `response_format={"type": "json_object"}` to the chat completions call.
- **`OpenAICompatibleApiClient`** (local/Ollama provider): no change — keep text instruction fallback.
- **`GoogleApiClient`**: pass `response_mime_type="application/json"` in the generation config.
- **`AnthropicApiClient`**: no change — schema enforcement already in place.

#### Prompt changes

When a model has `json_mode=True`, the closing "Return only valid JSON…" sentence should be omitted from prompts. The simplest approach is a conditional in the prompt-building layer (`prompt_builder.py`) that strips or skips the JSON instruction for `json_mode` models. The exact mechanism is left to the developer.

#### Acceptance Criteria

- [ ] `json_mode` field added to `ModelDefinition`; defaults to `False`
- [ ] `models.yml` sets `json_mode: true` for OpenAI, xAI, and Google models
- [ ] `OpenAICompatibleApiClient` passes `response_format={"type": "json_object"}` for OpenAI/xAI when `json_mode=True`
- [ ] `GoogleApiClient` passes `response_mime_type="application/json"` when `json_mode=True`
- [ ] JSON text instruction is omitted from prompts sent to `json_mode=True` models
- [ ] Ollama and unknown providers are unaffected (text instruction retained)
- [ ] Tests added or updated to cover the flag path for each affected client
- [ ] `make ci` passes

---

<!-- Add additional Task blocks as needed. -->
