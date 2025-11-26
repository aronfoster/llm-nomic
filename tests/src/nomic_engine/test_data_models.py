"""
Smoke tests for data models to ensure basic functionality.
"""

import pytest

from src.nomic_engine.data_models import (
    ChatMessage,
    Discussion,
    GameConfig,
    GameState,
    ModelDefinition,
    ModelLibrary,
    PlayerConfig,
    PlayerPersonality,
    Proposal,
    Rule,
    Vote,
)


def test_rule_creation():
    """Test that a Rule can be created with valid data."""
    rule = Rule(
        rule_id="101",
        text="All players must always abide by all the rules.",
        status="immutable",
    )
    assert rule.rule_id == "101"
    assert rule.status == "immutable"


def test_player_config_creation():
    """Test that PlayerConfig can be created with valid data."""
    player = PlayerConfig(name="Claude", model_id="claude-3-5-sonnet-20240620")
    assert player.name == "Claude"
    assert player.model_id == "claude-3-5-sonnet-20240620"


def test_player_config_default_personality():
    """Test that PlayerConfig defaults to friendly personality."""
    player = PlayerConfig(name="Claude", model_id="claude-3-5-sonnet-20240620")
    assert player.personality == PlayerPersonality.FRIENDLY
    # Enum inherits from str, so string comparison should also work
    assert player.personality == "friendly"


def test_player_config_custom_personality():
    """Test that PlayerConfig can be created with custom personality."""
    player = PlayerConfig(
        name="Claude",
        model_id="claude-3-5-sonnet-20240620",
        personality=PlayerPersonality.FRIENDLY,
    )
    assert player.name == "Claude"
    assert player.personality == PlayerPersonality.FRIENDLY
    assert player.personality == "friendly"


def test_player_config_machiavellian_personality():
    """Test PlayerConfig with explicit machiavellian personality."""
    player = PlayerConfig(
        name="Alice",
        model_id="gpt-4o",
        personality=PlayerPersonality.MACHIAVELLIAN,
    )
    assert player.personality == PlayerPersonality.MACHIAVELLIAN


def test_player_personality_enum_values():
    """Test that PlayerPersonality enum has expected values."""
    assert PlayerPersonality.MACHIAVELLIAN.value == "machiavellian"
    assert PlayerPersonality.FRIENDLY.value == "friendly"
    assert PlayerPersonality.NONE.value == "none"


def test_player_personality_enum_iteration():
    """Test that PlayerPersonality enum can be iterated."""
    personalities = list(PlayerPersonality)
    assert len(personalities) >= 3
    assert PlayerPersonality.MACHIAVELLIAN in personalities
    assert PlayerPersonality.FRIENDLY in personalities
    assert PlayerPersonality.NONE in personalities


def test_player_config_none_personality():
    """Test PlayerConfig with explicit none personality."""
    player = PlayerConfig(
        name="Alice",
        model_id="gpt-4o",
        personality=PlayerPersonality.NONE,
    )
    assert player.personality == PlayerPersonality.NONE
    assert player.personality == "none"


def test_player_config_personality_from_string():
    """Test that PlayerConfig accepts string values for personality."""
    # Pydantic should coerce valid string values to enum
    player = PlayerConfig(
        name="Alice",
        model_id="gpt-4o",
        personality="friendly",
    )
    assert player.personality == PlayerPersonality.FRIENDLY


def test_player_config_invalid_personality():
    """Test that PlayerConfig rejects invalid personality values."""
    with pytest.raises(ValueError):
        PlayerConfig(
            name="Alice",
            model_id="gpt-4o",
            personality="invalid_personality",
        )


def test_game_config_creation():
    """Test that GameConfig can be created with a list of players."""
    config = GameConfig(
        players=[
            PlayerConfig(name="Alice", model_id="gpt-4o"),
            PlayerConfig(name="Bob", model_id="claude-3-opus-20240229"),
        ]
    )
    assert len(config.players) == 2
    assert config.players[0].name == "Alice"
    assert config.target_score == 100


def test_game_config_custom_target_score():
    """Test that GameConfig allows overriding the target score."""
    config = GameConfig(
        players=[PlayerConfig(name="Alice", model_id="gpt-4o")],
        target_score=50,
    )

    assert config.target_score == 50


def test_game_state_creation():
    """Test that GameState can be created with valid data."""
    state = GameState(
        scores={"Alice": 0, "Bob": 0},
        current_player_name="Alice",
        move_number=1,
        turn_order=["Alice", "Bob"],
        next_proposal_id=301,
    )
    assert state.current_player_name == "Alice"
    assert state.move_number == 1
    assert len(state.scores) == 2
    assert state.next_proposal_id == 301
    assert state.target_score == 100


def test_game_state_custom_target_score():
    """Test that GameState can store a non-default target score."""
    state = GameState(
        scores={"Alice": 0, "Bob": 0},
        current_player_name="Alice",
        move_number=1,
        turn_order=["Alice", "Bob"],
        next_proposal_id=301,
        target_score=42,
    )

    assert state.target_score == 42


def test_proposal_creation():
    """Test that Proposal can be created with valid data."""
    proposal = Proposal(
        proposer_name="Alice",
        move_number=1,
        type="Add",
        new_text="Players must dance when they propose rules.",
        rationale="It makes the game more fun!",
    )
    assert proposal.proposer_name == "Alice"
    assert proposal.type == "Add"
    assert proposal.proposal_id is None
    assert proposal.target_rule_id is None
    assert proposal.private_thoughts is None


def test_proposal_with_private_thoughts():
    """Test that Proposal can have private_thoughts (for LLM players)."""
    proposal = Proposal(
        proposer_name="Claude",
        move_number=1,
        type="Add",
        new_text="Players must consider long-term strategy.",
        rationale="Strategic depth is important.",
        private_thoughts="This rule will help me build alliances early game.",
    )
    assert proposal.proposer_name == "Claude"
    assert proposal.type == "Add"
    expected_thoughts = "This rule will help me build alliances early game."
    assert proposal.private_thoughts == expected_thoughts


def test_discussion_creation():
    """Test that Discussion can be created with valid data."""
    # Test without private_thoughts (simulating human player)
    discussion_human = Discussion(
        player_name="Bob",
        text="I think this is a good proposal.",
    )
    assert discussion_human.player_name == "Bob"
    assert discussion_human.text == "I think this is a good proposal."
    assert discussion_human.private_thoughts is None


def test_discussion_with_private_thoughts():
    """Test that Discussion can have private_thoughts (for LLM players)."""
    discussion_llm = Discussion(
        player_name="Claude",
        text="I support this proposal.",
        private_thoughts="Supporting this will gain me favor.",
    )
    assert discussion_llm.player_name == "Claude"
    assert discussion_llm.text == "I support this proposal."
    expected_thoughts = "Supporting this will gain me favor."
    assert discussion_llm.private_thoughts == expected_thoughts


def test_discussion_abstention():
    """Test that Discussion can represent an abstention (empty text)."""
    discussion_abstain = Discussion(
        player_name="Charlie",
        text="",
        private_thoughts="I have nothing strategic to add here.",
    )
    assert discussion_abstain.player_name == "Charlie"
    assert discussion_abstain.text == ""
    assert discussion_abstain.private_thoughts is not None


def test_vote_creation():
    """Test that Vote can be created with valid data."""
    # Test without private_thoughts (simulating human player)
    vote_human = Vote(player_name="Bob", vote="YES", reason="I love dancing!")
    assert vote_human.player_name == "Bob"
    assert vote_human.vote == "YES"
    assert vote_human.private_thoughts is None

    # Test with private_thoughts (simulating LLM player)
    vote_llm = Vote(
        player_name="Alice",
        vote="NO",
        reason="This doesn't work",
        private_thoughts="Strategic analysis: this rule conflicts with 102",
    )
    assert vote_llm.player_name == "Alice"
    assert vote_llm.vote == "NO"
    expected_thoughts = "Strategic analysis: this rule conflicts with 102"
    assert vote_llm.private_thoughts == expected_thoughts


def test_model_definition_creation():
    """Test that ModelDefinition can be created with valid data."""
    model = ModelDefinition(
        id="claude-3-5-sonnet",
        provider="anthropic",
        api_model_id="claude-3-5-sonnet-20240620",
        env_key_name="ANTHROPIC_API_KEY",
    )
    assert model.id == "claude-3-5-sonnet"
    assert model.provider == "anthropic"


def test_model_library_creation():
    """Test that ModelLibrary can be created with a list of models."""
    library = ModelLibrary(
        models=[
            ModelDefinition(
                id="gpt-4o",
                provider="openai",
                api_model_id="gpt-4o",
                env_key_name="OPENAI_API_KEY",
            ),
            ModelDefinition(
                id="claude-3-5-sonnet",
                provider="anthropic",
                api_model_id="claude-3-5-sonnet-20240620",
                env_key_name="ANTHROPIC_API_KEY",
            ),
        ]
    )
    assert len(library.models) == 2
    assert library.models[0].id == "gpt-4o"


def test_chat_message_creation():
    """Test that ChatMessage can be created with valid data."""
    message = ChatMessage(role="user", content="Hello, world!")
    assert message.role == "user"
    assert message.content == "Hello, world!"

    # Test all valid roles
    system_msg = ChatMessage(
        role="system", content="You are a helpful assistant."
    )
    assert system_msg.role == "system"

    assistant_msg = ChatMessage(
        role="assistant", content="How can I help you?"
    )
    assert assistant_msg.role == "assistant"
