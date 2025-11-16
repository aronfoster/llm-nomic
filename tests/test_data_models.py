"""
Smoke tests for data models to ensure basic functionality.
"""

from src.nomic_engine.data_models import (
    GameConfig,
    GameState,
    ModelDefinition,
    ModelLibrary,
    PlayerConfig,
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


def test_vote_creation():
    """Test that Vote can be created with valid data."""
    vote = Vote(player_name="Bob", vote="YES", reason="I love dancing!")
    assert vote.player_name == "Bob"
    assert vote.vote == "YES"


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
