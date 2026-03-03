"""
Unit tests for the transmute_immutable_vote_mode flag behavior.

Covers:
1. IMMUTABLE→MUTABLE TRANSMUTE with flag="majority": uses majority even when
   vote_mode is "unanimous".
2. IMMUTABLE→MUTABLE TRANSMUTE with flag=null: falls back to vote_mode.
3. IMMUTABLE→MUTABLE TRANSMUTE with flag="unanimous" (default): uses unanimous.
4. MUTABLE→IMMUTABLE TRANSMUTE: flag is ignored; tally uses vote_mode.
5. Non-TRANSMUTE proposals: unaffected; always use vote_mode.
6. VoteResult.vote_mode reflects the effective mode used.
7. Flag validation: "unanimous" and "majority" accepted; null accepted;
   other strings rejected.
"""

from unittest.mock import Mock

import pytest

from src.nomic_engine.core.game_loop import GameLoop
from src.nomic_engine.core.game_manager import GameManager
from src.nomic_engine.data_models import (
    GameState,
    Proposal,
    ProposalType,
    Rule,
    RuleStatus,
    Vote,
)
from src.nomic_engine.utils.flag_schema import (
    clear_schema_cache,
    validate_flag_value,
    validate_state_updates,
)

# =========================================================================
# Fixtures
# =========================================================================


@pytest.fixture(autouse=True)
def _clear_cache() -> None:
    """Clear the schema cache before and after each test."""
    clear_schema_cache()
    yield  # type: ignore[misc]
    clear_schema_cache()


@pytest.fixture
def immutable_rule() -> Rule:
    """An IMMUTABLE rule that a TRANSMUTE proposal can target."""
    return Rule(
        rule_id="101",
        text="This rule is immutable.",
        status=RuleStatus.IMMUTABLE,
    )


@pytest.fixture
def mutable_rule() -> Rule:
    """A MUTABLE rule that a TRANSMUTE proposal can target."""
    return Rule(
        rule_id="201",
        text="This rule is mutable.",
        status=RuleStatus.MUTABLE,
    )


def _make_game_loop(
    flags: dict,
    target_rule: Rule,
) -> tuple[GameLoop, GameState]:
    """Build a GameLoop with the given flags and a rules_manager stub."""
    game_state = GameState(
        scores={"Alice": 0, "Bob": 0, "Charlie": 0},
        current_player_name="Alice",
        move_number=1,
        turn_order=["Alice", "Bob", "Charlie"],
        next_proposal_id=301,
        target_score=100,
        flags=flags,
    )

    manager = Mock(spec=GameManager)
    manager.game_state = game_state

    rules_manager = Mock()
    rules_manager.rules = [target_rule]
    rules_manager._find_rule_by_id = Mock(return_value=target_rule)
    manager.rules_manager = rules_manager

    log = Mock()
    log.log_transcript = Mock()
    log.log_event = Mock()
    manager.logger = log

    manager.save_game_state = Mock()
    manager.save_rules = Mock()
    manager.game_config = None

    game_loop = GameLoop(game_manager=manager, players=[])
    return game_loop, game_state


def _make_transmute_proposal(target_rule_id: str) -> Proposal:
    return Proposal(
        proposer_name="Alice",
        move_number=1,
        type=ProposalType.TRANSMUTE,
        proposal_id="301",
        target_rule_id=target_rule_id,
    )


def _make_add_proposal() -> Proposal:
    return Proposal(
        proposer_name="Alice",
        move_number=1,
        type=ProposalType.ADD,
        proposal_id="301",
        new_text="A new rule.",
    )


# =========================================================================
# 1. IMMUTABLE→MUTABLE TRANSMUTE, flag = "majority"
# =========================================================================


def test_immutable_transmute_majority_override_beats_unanimous(
    immutable_rule: Rule,
) -> None:
    """IMMUTABLE→MUTABLE TRANSMUTE with flag='majority' uses majority tally
    even when vote_mode is 'unanimous'.
    """
    flags = {
        "vote_mode": "unanimous",
        "transmute_immutable_vote_mode": "majority",
    }
    game_loop, _ = _make_game_loop(flags, immutable_rule)
    proposal = _make_transmute_proposal("101")

    # 2 YES, 1 NO → majority passes (2 > 1.5), unanimous would fail
    votes = [
        Vote(player_name="Alice", vote="YES"),
        Vote(player_name="Bob", vote="YES"),
        Vote(player_name="Charlie", vote="NO"),
    ]

    override = game_loop._resolve_effective_vote_mode(proposal)
    result = game_loop._tally_vote_results(votes, override)

    assert result.passed is True
    assert result.vote_mode == "majority"


def test_immutable_transmute_vote_result_vote_mode_reflects_override(
    immutable_rule: Rule,
) -> None:
    """VoteResult.vote_mode shows the override, not flags['vote_mode']."""
    flags = {
        "vote_mode": "unanimous",
        "transmute_immutable_vote_mode": "majority",
    }
    game_loop, _ = _make_game_loop(flags, immutable_rule)
    proposal = _make_transmute_proposal("101")

    votes = [Vote(player_name="Alice", vote="YES")]

    override = game_loop._resolve_effective_vote_mode(proposal)
    result = game_loop._tally_vote_results(votes, override)

    assert result.vote_mode == "majority"


def test_immutable_transmute_majority_override_all_yes_passes(
    immutable_rule: Rule,
) -> None:
    """IMMUTABLE→MUTABLE TRANSMUTE with majority override: all YES passes."""
    flags = {
        "vote_mode": "unanimous",
        "transmute_immutable_vote_mode": "majority",
    }
    game_loop, _ = _make_game_loop(flags, immutable_rule)
    proposal = _make_transmute_proposal("101")

    votes = [
        Vote(player_name="Alice", vote="YES"),
        Vote(player_name="Bob", vote="YES"),
        Vote(player_name="Charlie", vote="YES"),
    ]

    override = game_loop._resolve_effective_vote_mode(proposal)
    result = game_loop._tally_vote_results(votes, override)

    assert result.passed is True


# =========================================================================
# 2. IMMUTABLE→MUTABLE TRANSMUTE, flag = null → falls back to vote_mode
# =========================================================================


def test_immutable_transmute_null_flag_falls_back_unanimous(
    immutable_rule: Rule,
) -> None:
    """When flag is null, tally falls back to vote_mode (unanimous)."""
    flags = {
        "vote_mode": "unanimous",
        "transmute_immutable_vote_mode": None,
    }
    game_loop, _ = _make_game_loop(flags, immutable_rule)
    proposal = _make_transmute_proposal("101")

    # 2 YES, 1 NO → unanimous fails
    votes = [
        Vote(player_name="Alice", vote="YES"),
        Vote(player_name="Bob", vote="YES"),
        Vote(player_name="Charlie", vote="NO"),
    ]

    override = game_loop._resolve_effective_vote_mode(proposal)
    assert override is None  # no override; uses vote_mode
    result = game_loop._tally_vote_results(votes, override)

    assert result.passed is False
    assert result.vote_mode == "unanimous"


def test_immutable_transmute_null_flag_falls_back_majority(
    immutable_rule: Rule,
) -> None:
    """When flag is null and vote_mode is majority, majority tally is used."""
    flags = {
        "vote_mode": "majority",
        "transmute_immutable_vote_mode": None,
    }
    game_loop, _ = _make_game_loop(flags, immutable_rule)
    proposal = _make_transmute_proposal("101")

    # 2 YES, 1 NO → majority passes
    votes = [
        Vote(player_name="Alice", vote="YES"),
        Vote(player_name="Bob", vote="YES"),
        Vote(player_name="Charlie", vote="NO"),
    ]

    override = game_loop._resolve_effective_vote_mode(proposal)
    assert override is None
    result = game_loop._tally_vote_results(votes, override)

    assert result.passed is True
    assert result.vote_mode == "majority"


# =========================================================================
# 3. IMMUTABLE→MUTABLE TRANSMUTE, flag = "unanimous" (default)
# =========================================================================


def test_immutable_transmute_unanimous_override_no_no_votes_passes(
    immutable_rule: Rule,
) -> None:
    """Unanimous override: passes when no NO votes."""
    flags = {
        "vote_mode": "majority",
        "transmute_immutable_vote_mode": "unanimous",
    }
    game_loop, _ = _make_game_loop(flags, immutable_rule)
    proposal = _make_transmute_proposal("101")

    votes = [
        Vote(player_name="Alice", vote="YES"),
        Vote(player_name="Bob", vote="YES"),
        Vote(player_name="Charlie", vote="YES"),
    ]

    override = game_loop._resolve_effective_vote_mode(proposal)
    result = game_loop._tally_vote_results(votes, override)

    assert result.passed is True
    assert result.vote_mode == "unanimous"


def test_immutable_transmute_unanimous_override_any_no_fails(
    immutable_rule: Rule,
) -> None:
    """Unanimous override: fails when any NO vote is cast."""
    flags = {
        "vote_mode": "majority",
        "transmute_immutable_vote_mode": "unanimous",
    }
    game_loop, _ = _make_game_loop(flags, immutable_rule)
    proposal = _make_transmute_proposal("101")

    # 2 YES, 1 NO → would pass majority, but override forces unanimous → fails
    votes = [
        Vote(player_name="Alice", vote="YES"),
        Vote(player_name="Bob", vote="YES"),
        Vote(player_name="Charlie", vote="NO"),
    ]

    override = game_loop._resolve_effective_vote_mode(proposal)
    result = game_loop._tally_vote_results(votes, override)

    assert result.passed is False
    assert result.vote_mode == "unanimous"


# =========================================================================
# 4. MUTABLE→IMMUTABLE TRANSMUTE: flag is ignored; tally uses vote_mode
# =========================================================================


def test_mutable_transmute_ignores_flag_uses_unanimous_vote_mode(
    mutable_rule: Rule,
) -> None:
    """MUTABLE→IMMUTABLE TRANSMUTE: flag is ignored; uses vote_mode."""
    flags = {
        "vote_mode": "unanimous",
        "transmute_immutable_vote_mode": "majority",
    }
    game_loop, _ = _make_game_loop(flags, mutable_rule)
    proposal = _make_transmute_proposal("201")

    override = game_loop._resolve_effective_vote_mode(proposal)
    assert override is None  # flag not applied for MUTABLE target

    # 2 YES, 1 NO → unanimous fails (flag ignored)
    votes = [
        Vote(player_name="Alice", vote="YES"),
        Vote(player_name="Bob", vote="YES"),
        Vote(player_name="Charlie", vote="NO"),
    ]
    result = game_loop._tally_vote_results(votes, override)

    assert result.passed is False
    assert result.vote_mode == "unanimous"


def test_mutable_transmute_uses_majority_vote_mode_normally(
    mutable_rule: Rule,
) -> None:
    """MUTABLE→IMMUTABLE TRANSMUTE uses vote_mode (majority) normally."""
    flags = {
        "vote_mode": "majority",
        "transmute_immutable_vote_mode": "unanimous",
    }
    game_loop, _ = _make_game_loop(flags, mutable_rule)
    proposal = _make_transmute_proposal("201")

    override = game_loop._resolve_effective_vote_mode(proposal)
    assert override is None

    # 2 YES, 1 NO → majority passes
    votes = [
        Vote(player_name="Alice", vote="YES"),
        Vote(player_name="Bob", vote="YES"),
        Vote(player_name="Charlie", vote="NO"),
    ]
    result = game_loop._tally_vote_results(votes, override)

    assert result.passed is True
    assert result.vote_mode == "majority"


# =========================================================================
# 5. Non-TRANSMUTE proposals: always use vote_mode
# =========================================================================


def test_add_proposal_unaffected_by_transmute_flag(
    immutable_rule: Rule,
) -> None:
    """ADD proposals are unaffected by transmute_immutable_vote_mode."""
    flags = {
        "vote_mode": "unanimous",
        "transmute_immutable_vote_mode": "majority",
    }
    game_loop, _ = _make_game_loop(flags, immutable_rule)
    proposal = _make_add_proposal()

    override = game_loop._resolve_effective_vote_mode(proposal)
    assert override is None

    # 2 YES, 1 NO → unanimous fails
    votes = [
        Vote(player_name="Alice", vote="YES"),
        Vote(player_name="Bob", vote="YES"),
        Vote(player_name="Charlie", vote="NO"),
    ]
    result = game_loop._tally_vote_results(votes, override)

    assert result.passed is False
    assert result.vote_mode == "unanimous"


def test_amend_proposal_unaffected_by_transmute_flag(
    immutable_rule: Rule,
) -> None:
    """AMEND proposals are unaffected by transmute_immutable_vote_mode."""
    flags = {
        "vote_mode": "unanimous",
        "transmute_immutable_vote_mode": "majority",
    }
    game_loop, _ = _make_game_loop(flags, immutable_rule)
    proposal = Proposal(
        proposer_name="Alice",
        move_number=1,
        type=ProposalType.AMEND,
        proposal_id="301",
        target_rule_id="101",
        new_text="Amended text.",
    )

    override = game_loop._resolve_effective_vote_mode(proposal)
    assert override is None

    votes = [
        Vote(player_name="Alice", vote="YES"),
        Vote(player_name="Bob", vote="YES"),
        Vote(player_name="Charlie", vote="NO"),
    ]
    result = game_loop._tally_vote_results(votes, override)

    assert result.passed is False
    assert result.vote_mode == "unanimous"


def test_repeal_proposal_unaffected_by_transmute_flag(
    immutable_rule: Rule,
) -> None:
    """REPEAL proposals are unaffected by transmute_immutable_vote_mode."""
    flags = {
        "vote_mode": "unanimous",
        "transmute_immutable_vote_mode": "majority",
    }
    game_loop, _ = _make_game_loop(flags, immutable_rule)
    proposal = Proposal(
        proposer_name="Alice",
        move_number=1,
        type=ProposalType.REPEAL,
        proposal_id="301",
        target_rule_id="101",
    )

    override = game_loop._resolve_effective_vote_mode(proposal)
    assert override is None

    votes = [
        Vote(player_name="Alice", vote="YES"),
        Vote(player_name="Bob", vote="YES"),
        Vote(player_name="Charlie", vote="NO"),
    ]
    result = game_loop._tally_vote_results(votes, override)

    assert result.passed is False
    assert result.vote_mode == "unanimous"


# =========================================================================
# 6. _resolve_effective_vote_mode: edge cases
# =========================================================================


def test_transmute_no_target_rule_id_returns_none(
    immutable_rule: Rule,
) -> None:
    """TRANSMUTE without target_rule_id returns None (no override)."""
    flags = {
        "vote_mode": "unanimous",
        "transmute_immutable_vote_mode": "majority",
    }
    game_loop, _ = _make_game_loop(flags, immutable_rule)
    proposal = Proposal(
        proposer_name="Alice",
        move_number=1,
        type=ProposalType.TRANSMUTE,
        proposal_id="301",
        # No target_rule_id
    )

    override = game_loop._resolve_effective_vote_mode(proposal)
    assert override is None


def test_transmute_rule_not_found_returns_none(
    immutable_rule: Rule,
) -> None:
    """TRANSMUTE where target rule is not found returns None."""
    flags = {
        "vote_mode": "unanimous",
        "transmute_immutable_vote_mode": "majority",
    }
    game_loop, _ = _make_game_loop(flags, immutable_rule)
    # Override _find_rule_by_id to return None
    game_loop.game_manager.rules_manager._find_rule_by_id = Mock(
        return_value=None
    )
    proposal = _make_transmute_proposal("999")

    override = game_loop._resolve_effective_vote_mode(proposal)
    assert override is None


# =========================================================================
# 7. Flag validation
# =========================================================================


class TestTransmuteImmutableVoteModeValidation:
    """Flag schema validation for transmute_immutable_vote_mode."""

    def test_accepts_unanimous(self) -> None:
        """'unanimous' is a valid value."""
        validate_flag_value("transmute_immutable_vote_mode", "unanimous")

    def test_accepts_majority(self) -> None:
        """'majority' is a valid value."""
        validate_flag_value("transmute_immutable_vote_mode", "majority")

    def test_accepts_null(self) -> None:
        """None is valid (nullable=true)."""
        validate_flag_value("transmute_immutable_vote_mode", None)

    def test_rejects_invalid_string(self) -> None:
        """Unknown string values are rejected."""
        with pytest.raises(ValueError, match="not valid"):
            validate_flag_value("transmute_immutable_vote_mode", "consensus")

    def test_rejects_integer(self) -> None:
        """Integer values are rejected (type mismatch)."""
        with pytest.raises(ValueError, match="expects type"):
            validate_flag_value("transmute_immutable_vote_mode", 1)

    def test_rejects_boolean(self) -> None:
        """Boolean values are rejected (type mismatch)."""
        with pytest.raises(ValueError, match="expects type"):
            validate_flag_value("transmute_immutable_vote_mode", True)

    def test_state_updates_accepts_unanimous(self) -> None:
        """StateUpdates with value 'unanimous' is valid."""
        validate_state_updates(
            {"flags": {"transmute_immutable_vote_mode": "unanimous"}}
        )

    def test_state_updates_accepts_majority(self) -> None:
        """StateUpdates with value 'majority' is valid."""
        validate_state_updates(
            {"flags": {"transmute_immutable_vote_mode": "majority"}}
        )

    def test_state_updates_accepts_null(self) -> None:
        """StateUpdates with value null is valid."""
        validate_state_updates(
            {"flags": {"transmute_immutable_vote_mode": None}}
        )

    def test_state_updates_rejects_invalid_string(self) -> None:
        """StateUpdates with invalid string raises ValueError."""
        with pytest.raises(ValueError, match="not valid"):
            validate_state_updates(
                {"flags": {"transmute_immutable_vote_mode": "supermajority"}}
            )

    def test_null_skips_valid_values_enforcement(self) -> None:
        """None is accepted even though valid_values lists only strings."""
        # Confirms nullable path skips valid_values checking
        validate_flag_value("transmute_immutable_vote_mode", None)
