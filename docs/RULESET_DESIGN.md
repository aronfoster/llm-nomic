# Ruleset Design Documentation

## Purpose

This document explains how the LLM-Nomic ruleset differs from Peter Suber's original 1982 Nomic rules and why those changes were necessary for engine-based play with LLM participants.

**Core Philosophy**: Stay as faithful to Suber's original design as possible. Diverge only when engine constraints make it impossible to implement the original rule, or when the original rule references capabilities the engine doesn't have.

## Reference

Original Nomic rules: [Peter Suber's Nomic](http://legacy.earlham.edu/~peters/writing/nomic.htm)

---

## Changes from Original Rules

### 1. Rule 111 — Discussion Phase (SIMPLIFIED)

**Original (Suber's Rule 111)**:
> "If a rule change as proposed is unclear, ambiguous, paradoxical or destructive of play, is held by a player to consist of two or more rule changes compounded or to be an amendment that makes no difference, or it otherwise held to be of questionable value, then the other players can suggest amendment or argue against the rule change before the vote. The proponent, however, decides the final form in which the proposal is to be voted on and chooses the time to end debate and vote."

**Current (Engine Rule 111)**:
> "Each player may append one short comment on the proposal before votes are cast, including the proposer. The proposer may revise the proposal once based on comments before voting proceeds."

**Rationale**: 
- The original rule describes organic human discussion dynamics that don't map to the engine's structured turn phases
- "Unclear, ambiguous, paradoxical" are subjective judgments that would require human moderation in every turn
- The engine implements a fixed discussion-then-revision-then-vote sequence; players can't dynamically "choose the time to end debate"

**Tradeoff**: 
Lost the original's flexibility around extended debate and the explicit UNCLEAR/AMBIGUOUS triggering mechanism. Gained a clean, automatable discussion phase that works for both humans and LLMs.

---

### 2. Rule 117 — Judge Infrastructure (ADDED)

**Original**: No equivalent rule in Suber's initial set

**Current (Engine Rule 117)**:
> "An impartial Judge will veto an adopted proposal before it takes effect if the game engine cannot support it, in which case points are awarded as if it passed but no change is made to the rules. The Judge also determines score changes each turn per the applicable rules, and updates engine state when rules require it."

**Rationale**:
- Suber's game assumes human players who can intuitively recognize when a rule can't be executed
- The engine needs explicit machinery to handle proposals that would break the game state
- The judge role (human or LLM) is engine infrastructure, not a gameplay mechanic
- Veto scope is deliberately narrow: ONLY for engine capability limitations, NOT for rule conflicts or violations (those are handled by existing rules 110, 211)

**Tradeoff**:
Adds a safeguard that doesn't exist in the original, but only for technical feasibility issues that couldn't arise in human play.

---

### 3. Rule 202 — Scoring Mechanism (CHANGED)

**Original (Suber's Rule 202)**:
> "One turn consists of two parts, in the order: (1) proposing one rule change and having it voted on, and (2) throwing one die once and adding the number of points on its face to one's score."

**Current (Engine Rule 202)**:
> "One turn consists of two parts in this order: (1) proposing one rule-change and having it voted on, and (2) adding 3 points to the proposer's score."

**Rationale**:
- Die rolls require a randomize feature to be added to the scoring judge
- Simplified to a flat 3 points per turn, regardless of vote outcome
- This matches the expected value of a d6 roll (3.5, rounded down)
- **Critically, this preserves the original's unconditional scoring** — players always gain points, win or lose

**Tradeoff**:
The original's randomness served as a balancing force against pure-strategy dominance and created turn-to-turn score variance. The deterministic scoring removes both of these. However, this is the minimal viable adaptation — it preserves the original's most important property (unconditional forward progress) while being deterministic and auditable.

---

### 4. Original Rule 210 — Teams and Conspiracy (DELETED)

**Original (Suber's Rule 210)**:
> "Players may not conspire or consult on the making of future rule changes unless they are teammates."

**Current**: Rule deleted entirely

**Rationale**:
- The engine has no concept of "teams" as a feature
- LLMs cannot conspire between turns (no side channels exist)
- Human players can trivially conspire via any external communication method, and the engine cannot detect it
- The rule references infrastructure that doesn't exist and prohibits behavior that's impossible to enforce

**Tradeoff**:
When teams are eventually implemented (if ever), the conspiracy prohibition may or may not make sense to reinstate. It might be more interesting to explicitly allow team coordination as a feature rather than policing it.

---

### 5. Original Rules 212-213 — Judge Selection and Paradox Victory (DELETED)

**Original (Suber's Rule 212)**:
> "If players disagree about the legality of a move or the interpretation or application of a rule, the player to the right of the one moving is to be the Judge and decide the question. (Such a process is called invoking Judgment.) The Judge's Judgment may be overruled only by a unanimous vote of the other players, taken before the next turn is begun. [...] New Judges are not bound by the decisions of old Judges."

**Original (Suber's Rule 213)**:
> "If the rules are changed so that further play is impossible, or if the legality of a move is impossible to determine with finality, or if by the Judge's best reasoning, not overruled, a move appears equally legal and illegal, then the first player who is unable to complete a turn is the winner."

**Current**: Both rules deleted entirely

**Rationale**:

**Rule 212 (Judge Selection)**:
- Suber's rotating judge system is beautiful game theory: peer judgment with accountability loops, overruling mechanisms, and fresh perspectives each turn
- Implementing this in the engine would be difficult:
  - Detecting when judgment needs to be invoked
  - Managing judge rotation and exclusion rules (not during your own turn or teammate's turn)
  - Implementing unanimous override votes mid-turn
  - Handling cascading judge replacements when overruled
- This level of dynamic role-switching doesn't map to the engine's fixed judge infrastructure

**Rule 213 (Paradox Victory)**:
- Promises a win condition the engine cannot currently deliver
- Detecting "play is impossible" or "move appears equally legal and illegal" requires sophisticated paradox detection
- The engine would need to have a player, judge, or other participant recognize a potential unresolvable game states, then go to a new game-end condition
- Having an undeliverable win condition in the ruleset is worse than having no rule at all

**Tradeoff**:

Suber's judge system created emergent complexity: players could strategically time proposals to get favorable judges, or craft proposals specifically to trigger judgment disputes. All of that is lost.

Similarly, paradox-as-strategy is lost — players can't deliberately engineer impossible game states to trigger victory.

These are significant strategic dimensions removed from the game. When/if the engine eventually supports graceful paradox detection, Rule 213 could be reinstated.

---

## Summary of Changes

| Original Rule | Current Status | Change Type |
|---------------|----------------|-------------|
| 111 | Simplified | Structural simplification for engine automation |
| 117 | Added | New engine infrastructure |
| 202 | Modified | Die roll → consistent points |
| 210 | Deleted | Teams/conspiracy detection not supported |
| 212 | Deleted | Rotating judge system replaced by fixed judge |
| 213 | Deleted | Paradox victory not supported |

Rules 101-110, 112-116 remain unchanged from Suber's original.

Mutable rules 201, 203-209 remain unchanged from Suber's original (with 211 renumbered to 210 after deletions).

---

## Known Limitations

Features explicitly **not** supported in the current engine:

1. **Paradox detection**: The engine cannot gracefully recognize when the game state becomes unresolvable
2. **Teams**: No concept of team membership or team-based rules
3. **Dynamic judge rotation**: Judge is a fixed role (human or LLM), not a rotating player responsibility
4. **Organic debate timing**: Discussion happens in a fixed phase, not dynamically during proposal presentation

---

## Design Principles for Future Changes

When considering whether to add/remove rules:

1. **Engine constraints are hard boundaries**: If the engine can't track it, the rule shouldn't promise it
2. **Suber's conflict resolution machinery works**: Rules 110 and 210 handle conflicts; the judge should not veto conflicting proposals
3. **Unenforceable rules are worse than no rules**: Don't include prohibitions the engine can't detect

---

*This document should be updated whenever the default ruleset changes. The goal is to maintain intellectual honesty about what the game is versus what it could theoretically be.*