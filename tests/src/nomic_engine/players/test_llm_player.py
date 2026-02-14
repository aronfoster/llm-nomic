"""
Unit tests for LLMPlayer functionality with stateful conversation history.

Tests cover:
- vote() method
- discuss() method
- propose() method
- revise() method
- Stateful conversation history management
"""

from unittest.mock import MagicMock, patch

import pytest

from src.nomic_engine.data_models import (
    ChatMessage,
    Discussion,
    GameState,
    ModelDefinition,
    Proposal,
    ProposalType,
    Rule,
    RuleStatus,
)
from src.nomic_engine.players.llm_player import LLMPlayer


@pytest.fixture
def model_config():
    """Create a test model configuration."""
    return ModelDefinition(
        id="test-model",
        provider="local",
        api_model_id="http://localhost:11434",
        env_key_name=None,
    )


@pytest.fixture
def game_state():
    """Create a test game state."""
    return GameState(
        scores={"Alice": 10, "Bob": 5},
        current_player_name="Alice",
        move_number=1,
        turn_order=["Alice", "Bob", "TestPlayer"],
        next_proposal_id=301,
    )


@pytest.fixture
def proposal():
    """Create a test proposal."""
    return Proposal(
        proposer_name="Alice",
        move_number=1,
        type=ProposalType.ADD,
        proposal_id="301",
        new_text="New rule text",
        rationale="This is a good rule",
    )


@pytest.fixture
def rules():
    """Create a test rules list."""
    return [
        Rule(rule_id="101", text="Rule 101 text", status=RuleStatus.IMMUTABLE),
        Rule(rule_id="102", text="Rule 102 text", status=RuleStatus.MUTABLE),
    ]


class TestLLMPlayerVote:
    """Tests for LLMPlayer.vote() method."""

    @patch("src.nomic_engine.players.llm_player.PromptBuilder")
    @patch("src.nomic_engine.players.llm_player.ApiClient")
    @patch("src.nomic_engine.players.llm_player.parse_vote_response")
    def test_vote_success_first_try(
        self,
        mock_parse,
        mock_api_client_class,
        mock_prompt_builder_class,
        model_config,
        game_state,
        proposal,
        rules,
    ):
        """Test successful vote on the first attempt."""
        # Setup mocks
        mock_api_instance = MagicMock()
        mock_api_client_class.return_value = mock_api_instance

        mock_prompt_builder_instance = MagicMock()
        mock_prompt_builder_class.return_value = mock_prompt_builder_instance

        # Mock the prompt builder to return a single ChatMessage for vote
        mock_vote_instruction = ChatMessage(
            role="user", content="Vote instruction prompt"
        )
        mock_prompt_builder_instance.build_vote_instruction.return_value = (
            mock_vote_instruction
        )

        # Mock the API client to return valid JSON
        valid_json_response = """{
            "private_thoughts": "Strategic analysis here",
            "public_reason": "This is good for the game",
            "vote": "YES"
        }"""
        mock_api_instance.get_completion.return_value = valid_json_response

        # Mock the parser to return valid data
        mock_parse.return_value = {
            "private_thoughts": "Strategic analysis here",
            "public_reason": "This is good for the game",
            "vote": "YES",
        }

        # Create player and set up initial history (vote continues)
        player = LLMPlayer("TestPlayer", model_config)
        # Simulate that discuss() was already called and set up history
        player.turn_history = [
            ChatMessage(role="system", content="System prompt from discuss"),
            ChatMessage(role="assistant", content="Discussion response"),
        ]

        vote = player.vote(proposal, game_state, rules)

        # Assertions
        assert vote.player_name == "TestPlayer"
        assert vote.vote == "YES"
        assert vote.reason == "This is good for the game"
        assert vote.private_thoughts == "Strategic analysis here"

        # Verify API was called only once
        assert mock_api_instance.get_completion.call_count == 1

        # Verify parser was called only once
        assert mock_parse.call_count == 1
        mock_parse.assert_called_with(valid_json_response)

    @patch("src.nomic_engine.players.llm_player.PromptBuilder")
    @patch("src.nomic_engine.players.llm_player.ApiClient")
    @patch("src.nomic_engine.players.llm_player.parse_vote_response")
    def test_vote_success_after_retry(
        self,
        mock_parse,
        mock_api_client_class,
        mock_prompt_builder_class,
        model_config,
        game_state,
        proposal,
        rules,
    ):
        """Test successful vote after one retry."""
        # Setup mocks
        mock_api_instance = MagicMock()
        mock_api_client_class.return_value = mock_api_instance

        mock_prompt_builder_instance = MagicMock()
        mock_prompt_builder_class.return_value = mock_prompt_builder_instance

        # Mock the prompt builder to return a single ChatMessage
        mock_vote_instruction = ChatMessage(
            role="user", content="Vote instruction prompt"
        )
        mock_prompt_builder_instance.build_vote_instruction.return_value = (
            mock_vote_instruction
        )

        # Mock the API client to return bad JSON first, then good JSON
        bad_json_response = "This is not valid JSON"
        good_json_response = """{
            "private_thoughts": "Better analysis now",
            "public_reason": "I reconsider my position",
            "vote": "NO"
        }"""
        mock_api_instance.get_completion.side_effect = [
            bad_json_response,
            good_json_response,
        ]

        # Mock the parser: raise ValueError first, then return valid data
        mock_parse.side_effect = [
            ValueError("Response is not valid JSON. Error: ..."),
            {
                "private_thoughts": "Better analysis now",
                "public_reason": "I reconsider my position",
                "vote": "NO",
            },
        ]

        # Create player with initial history
        player = LLMPlayer("TestPlayer", model_config)
        player.turn_history = [
            ChatMessage(role="system", content="System prompt"),
        ]

        vote = player.vote(proposal, game_state, rules)

        # Assertions
        assert vote.player_name == "TestPlayer"
        assert vote.vote == "NO"
        assert vote.reason == "I reconsider my position"

        # Verify API was called twice
        assert mock_api_instance.get_completion.call_count == 2

        # Verify parser was called twice
        assert mock_parse.call_count == 2

        # Verify history contains retry messages
        # system, vote_instruction, assistant (bad), user (retry)
        assert len(player.turn_history) >= 4
        # After success, history should have the valid response appended
        assert player.turn_history[-1].role == "assistant"

    @patch("src.nomic_engine.players.llm_player.PromptBuilder")
    @patch("src.nomic_engine.players.llm_player.ApiClient")
    @patch("src.nomic_engine.players.llm_player.parse_vote_response")
    def test_vote_failure_max_retries(
        self,
        mock_parse,
        mock_api_client_class,
        mock_prompt_builder_class,
        model_config,
        game_state,
        proposal,
        rules,
    ):
        """Test that player returns ABSTAIN after exhausting retries."""
        # Setup mocks
        mock_api_instance = MagicMock()
        mock_api_client_class.return_value = mock_api_instance

        mock_prompt_builder_instance = MagicMock()
        mock_prompt_builder_class.return_value = mock_prompt_builder_instance

        # Mock the prompt builder to return a single ChatMessage
        mock_vote_instruction = ChatMessage(
            role="user", content="Vote instruction prompt"
        )
        mock_prompt_builder_instance.build_vote_instruction.return_value = (
            mock_vote_instruction
        )

        # Mock the API client to always return bad JSON
        bad_json_response = "This is consistently bad JSON {{{{{{"
        mock_api_instance.get_completion.return_value = bad_json_response

        # Mock the parser to always raise ValueError
        mock_parse.side_effect = ValueError("Response is not valid JSON")

        # Create player with initial history
        player = LLMPlayer("TestPlayer", model_config)
        player.turn_history = [
            ChatMessage(role="system", content="System prompt"),
        ]

        vote = player.vote(proposal, game_state, rules)

        # Assertions - should return ABSTAIN with error message
        assert vote.player_name == "TestPlayer"
        assert vote.vote == "ABSTAIN"
        assert vote.reason == "LLM Error: Failed to generate valid vote."

        # Verify API was called MAX_VOTE_RETRIES times (2)
        assert (
            mock_api_instance.get_completion.call_count
            == player.tuning.max_vote_retries
        )

        # Verify parser was called MAX_VOTE_RETRIES times
        assert mock_parse.call_count == player.tuning.max_vote_retries

    @patch("src.nomic_engine.players.llm_player.PromptBuilder")
    @patch("src.nomic_engine.players.llm_player.ApiClient")
    def test_vote_api_error_then_success(
        self,
        mock_api_client_class,
        mock_prompt_builder_class,
        model_config,
        game_state,
        proposal,
        rules,
    ):
        """Test that player retries after API errors (None response)."""
        # Setup mocks
        mock_api_instance = MagicMock()
        mock_api_client_class.return_value = mock_api_instance

        mock_prompt_builder_instance = MagicMock()
        mock_prompt_builder_class.return_value = mock_prompt_builder_instance

        # Mock the prompt builder to return a single ChatMessage
        mock_vote_instruction = ChatMessage(
            role="user", content="Vote instruction prompt"
        )
        mock_prompt_builder_instance.build_vote_instruction.return_value = (
            mock_vote_instruction
        )

        # Mock the API client: first returns None (API error), second succeeds
        good_json_response = """{
            "private_thoughts": "Analysis",
            "public_reason": "Reason",
            "vote": "ABSTAIN"
        }"""
        mock_api_instance.get_completion.side_effect = [
            None,
            good_json_response,
        ]

        # Create player with initial history
        player = LLMPlayer("TestPlayer", model_config)
        player.turn_history = [
            ChatMessage(role="system", content="System prompt"),
        ]

        vote = player.vote(proposal, game_state, rules)

        # Assertions
        assert vote.player_name == "TestPlayer"
        assert vote.vote == "ABSTAIN"
        assert vote.reason == "Reason"

        # Verify API was called twice
        assert mock_api_instance.get_completion.call_count == 2

    @patch("src.nomic_engine.players.llm_player.PromptBuilder")
    @patch("src.nomic_engine.players.llm_player.ApiClient")
    def test_vote_all_api_errors(
        self,
        mock_api_client_class,
        mock_prompt_builder_class,
        model_config,
        game_state,
        proposal,
        rules,
    ):
        """Test that player returns ABSTAIN when API consistently fails."""
        # Setup mocks
        mock_api_instance = MagicMock()
        mock_api_client_class.return_value = mock_api_instance

        mock_prompt_builder_instance = MagicMock()
        mock_prompt_builder_class.return_value = mock_prompt_builder_instance

        # Mock the prompt builder to return a single ChatMessage
        mock_vote_instruction = ChatMessage(
            role="user", content="Vote instruction prompt"
        )
        mock_prompt_builder_instance.build_vote_instruction.return_value = (
            mock_vote_instruction
        )

        # Mock the API client to always return None (API error)
        mock_api_instance.get_completion.return_value = None

        # Create player with initial history
        player = LLMPlayer("TestPlayer", model_config)
        player.turn_history = [
            ChatMessage(role="system", content="System prompt"),
        ]

        vote = player.vote(proposal, game_state, rules)

        # Assertions - should return ABSTAIN with error message
        assert vote.player_name == "TestPlayer"
        assert vote.vote == "ABSTAIN"
        assert vote.reason == "LLM Error: Failed to generate valid vote."

        # Verify API was called MAX_VOTE_RETRIES times
        assert (
            mock_api_instance.get_completion.call_count
            == player.tuning.max_vote_retries
        )

    @patch("src.nomic_engine.players.llm_player.PromptBuilder")
    @patch("src.nomic_engine.players.llm_player.ApiClient")
    @patch("src.nomic_engine.players.llm_player.parse_vote_response")
    def test_vote_prompt_builder_called_correctly(
        self,
        mock_parse,
        mock_api_client_class,
        mock_prompt_builder_class,
        model_config,
        game_state,
        proposal,
        rules,
    ):
        """Test that PromptBuilder is called with correct arguments."""
        # Setup mocks
        mock_api_instance = MagicMock()
        mock_api_client_class.return_value = mock_api_instance

        mock_prompt_builder_instance = MagicMock()
        mock_prompt_builder_class.return_value = mock_prompt_builder_instance

        # Mock the prompt builder to return a single ChatMessage
        mock_vote_instruction = ChatMessage(
            role="user", content="Vote instruction prompt"
        )
        mock_prompt_builder_instance.build_vote_instruction.return_value = (
            mock_vote_instruction
        )

        # Mock successful API response
        mock_api_instance.get_completion.return_value = (
            '{"vote":"YES","public_reason":"Good",'
            '"private_thoughts":"Analysis"}'
        )
        mock_parse.return_value = {
            "vote": "YES",
            "public_reason": "Good",
            "private_thoughts": "Analysis",
        }

        # Create player with initial history
        player = LLMPlayer("TestPlayer", model_config)
        player.turn_history = [
            ChatMessage(role="system", content="System prompt"),
        ]

        discussions = [Discussion(player_name="Alice", text="Good proposal")]
        player.vote(proposal, game_state, rules, discussions=discussions)

        # Verify PromptBuilder.build_vote_instruction was called correctly
        mock_prompt_builder_instance.build_vote_instruction.assert_called_once_with(
            proposal=proposal,
            discussions=discussions,
            rules=rules,
            player_name="TestPlayer",
        )


class TestLLMPlayerDiscuss:
    """Tests for LLMPlayer.discuss() method."""

    @patch("src.nomic_engine.players.llm_player.PromptBuilder")
    @patch("src.nomic_engine.players.llm_player.ApiClient")
    @patch("src.nomic_engine.players.llm_player.parse_discussion_response")
    def test_discuss_success_first_try(
        self,
        mock_parse,
        mock_api_client_class,
        mock_prompt_builder_class,
        model_config,
        game_state,
        proposal,
        rules,
    ):
        """Test successful discussion on the first attempt."""
        # Setup mocks
        mock_api_instance = MagicMock()
        mock_api_client_class.return_value = mock_api_instance

        mock_prompt_builder_instance = MagicMock()
        mock_prompt_builder_class.return_value = mock_prompt_builder_instance

        # Mock the prompt builder to return a single system ChatMessage
        mock_system_message = ChatMessage(
            role="system", content="Discusser system prompt"
        )
        pb = mock_prompt_builder_instance
        pb.build_discusser_system_message.return_value = mock_system_message

        # Mock the API client to return valid JSON
        valid_json_response = """{
            "private_thoughts": "Strategic analysis here",
            "discussion_text": "I think this proposal has merit."
        }"""
        mock_api_instance.get_completion.return_value = valid_json_response

        # Mock the parser to return valid data
        mock_parse.return_value = {
            "private_thoughts": "Strategic analysis here",
            "discussion_text": "I think this proposal has merit.",
        }

        # Create player and discuss
        player = LLMPlayer("TestPlayer", model_config)
        result = player.discuss(proposal, game_state, rules)

        # Assertions - now returns Discussion object
        assert isinstance(result, Discussion)
        assert result.text == "I think this proposal has merit."
        assert result.player_name == "TestPlayer"

        # Verify API was called only once
        assert mock_api_instance.get_completion.call_count == 1

        # Verify parser was called only once
        assert mock_parse.call_count == 1
        mock_parse.assert_called_with(valid_json_response)

    @patch("src.nomic_engine.players.llm_player.PromptBuilder")
    @patch("src.nomic_engine.players.llm_player.ApiClient")
    @patch("src.nomic_engine.players.llm_player.parse_discussion_response")
    def test_discuss_empty_string_returns_abstain(
        self,
        mock_parse,
        mock_api_client_class,
        mock_prompt_builder_class,
        model_config,
        game_state,
        proposal,
        rules,
    ):
        """Test empty discussion_text returns Discussion with empty text."""
        # Setup mocks
        mock_api_instance = MagicMock()
        mock_api_client_class.return_value = mock_api_instance

        mock_prompt_builder_instance = MagicMock()
        mock_prompt_builder_class.return_value = mock_prompt_builder_instance

        mock_system_message = ChatMessage(
            role="system", content="Discusser system prompt"
        )
        pb = mock_prompt_builder_instance
        pb.build_discusser_system_message.return_value = mock_system_message

        mock_api_instance.get_completion.return_value = """{
            "private_thoughts": "I prefer to stay silent.",
            "discussion_text": ""
        }"""

        mock_parse.return_value = {
            "private_thoughts": "I prefer to stay silent.",
            "discussion_text": "",
        }

        # Create player and discuss
        player = LLMPlayer("TestPlayer", model_config)
        result = player.discuss(proposal, game_state, rules)

        # Should return Discussion with empty text for abstention
        assert isinstance(result, Discussion)
        assert result.text == ""
        assert result.player_name == "TestPlayer"

    @patch("src.nomic_engine.players.llm_player.PromptBuilder")
    @patch("src.nomic_engine.players.llm_player.ApiClient")
    @patch("src.nomic_engine.players.llm_player.parse_discussion_response")
    def test_discuss_success_after_retry(
        self,
        mock_parse,
        mock_api_client_class,
        mock_prompt_builder_class,
        model_config,
        game_state,
        proposal,
        rules,
    ):
        """Test successful discussion after one retry."""
        # Setup mocks
        mock_api_instance = MagicMock()
        mock_api_client_class.return_value = mock_api_instance

        mock_prompt_builder_instance = MagicMock()
        mock_prompt_builder_class.return_value = mock_prompt_builder_instance

        mock_system_message = ChatMessage(
            role="system", content="Discusser system prompt"
        )
        pb = mock_prompt_builder_instance
        pb.build_discusser_system_message.return_value = mock_system_message

        # Mock the API client to return bad JSON first, then good JSON
        bad_json_response = "This is not valid JSON"
        good_json_response = """{
            "private_thoughts": "Better analysis now",
            "discussion_text": "Let me reconsider..."
        }"""
        mock_api_instance.get_completion.side_effect = [
            bad_json_response,
            good_json_response,
        ]

        # Mock the parser: raise ValueError first, then return valid data
        mock_parse.side_effect = [
            ValueError("Response is not valid JSON. Error: ..."),
            {
                "private_thoughts": "Better analysis now",
                "discussion_text": "Let me reconsider...",
            },
        ]

        # Create player and discuss
        player = LLMPlayer("TestPlayer", model_config)
        result = player.discuss(proposal, game_state, rules)

        # Assertions - now returns Discussion object
        assert isinstance(result, Discussion)
        assert result.text == "Let me reconsider..."

        # Verify API was called twice
        assert mock_api_instance.get_completion.call_count == 2

        # Verify parser was called twice
        assert mock_parse.call_count == 2

        # Verify history contains retry messages
        # system, assistant (bad), user (retry), then another call
        assert len(player.turn_history) >= 3

    @patch("src.nomic_engine.players.llm_player.PromptBuilder")
    @patch("src.nomic_engine.players.llm_player.ApiClient")
    @patch("src.nomic_engine.players.llm_player.parse_discussion_response")
    def test_discuss_failure_max_retries_returns_abstain(
        self,
        mock_parse,
        mock_api_client_class,
        mock_prompt_builder_class,
        model_config,
        game_state,
        proposal,
        rules,
    ):
        """Test player returns Discussion with empty text after retries."""
        # Setup mocks
        mock_api_instance = MagicMock()
        mock_api_client_class.return_value = mock_api_instance

        mock_prompt_builder_instance = MagicMock()
        mock_prompt_builder_class.return_value = mock_prompt_builder_instance

        mock_system_message = ChatMessage(
            role="system", content="Discusser system prompt"
        )
        pb = mock_prompt_builder_instance
        pb.build_discusser_system_message.return_value = mock_system_message

        # Mock the API client to always return bad JSON
        bad_json_response = "This is consistently bad JSON {{{{{{"
        mock_api_instance.get_completion.return_value = bad_json_response

        # Mock the parser to always raise ValueError
        mock_parse.side_effect = ValueError("Response is not valid JSON")

        # Create player and discuss
        player = LLMPlayer("TestPlayer", model_config)
        result = player.discuss(proposal, game_state, rules)

        # Assertions - Discussion with empty text (abstain fallback)
        assert isinstance(result, Discussion)
        assert result.text == ""
        assert result.player_name == "TestPlayer"

        # Verify API was called MAX_DISCUSS_RETRIES times (2)
        assert (
            mock_api_instance.get_completion.call_count
            == player.tuning.max_discuss_retries
        )

        # Verify parser was called MAX_DISCUSS_RETRIES times
        assert mock_parse.call_count == player.tuning.max_discuss_retries

    @patch("src.nomic_engine.players.llm_player.PromptBuilder")
    @patch("src.nomic_engine.players.llm_player.ApiClient")
    def test_discuss_all_api_errors_returns_abstain(
        self,
        mock_api_client_class,
        mock_prompt_builder_class,
        model_config,
        game_state,
        proposal,
        rules,
    ):
        """Test player returns Discussion with empty text on API errors."""
        # Setup mocks
        mock_api_instance = MagicMock()
        mock_api_client_class.return_value = mock_api_instance

        mock_prompt_builder_instance = MagicMock()
        mock_prompt_builder_class.return_value = mock_prompt_builder_instance

        mock_system_message = ChatMessage(
            role="system", content="Discusser system prompt"
        )
        pb = mock_prompt_builder_instance
        pb.build_discusser_system_message.return_value = mock_system_message

        # Mock the API client to always return None (API error)
        mock_api_instance.get_completion.return_value = None

        # Create player and discuss
        player = LLMPlayer("TestPlayer", model_config)
        result = player.discuss(proposal, game_state, rules)

        # Assertions - Discussion with empty text (abstain fallback)
        assert isinstance(result, Discussion)
        assert result.text == ""
        assert result.player_name == "TestPlayer"

        # Verify API was called MAX_DISCUSS_RETRIES times
        assert (
            mock_api_instance.get_completion.call_count
            == player.tuning.max_discuss_retries
        )

    @patch("src.nomic_engine.players.llm_player.PromptBuilder")
    @patch("src.nomic_engine.players.llm_player.ApiClient")
    @patch("src.nomic_engine.players.llm_player.parse_discussion_response")
    def test_discuss_prompt_builder_called_correctly(
        self,
        mock_parse,
        mock_api_client_class,
        mock_prompt_builder_class,
        model_config,
        game_state,
        proposal,
        rules,
    ):
        """Test that PromptBuilder is called with correct arguments."""
        # Setup mocks
        mock_api_instance = MagicMock()
        mock_api_client_class.return_value = mock_api_instance

        mock_prompt_builder_instance = MagicMock()
        mock_prompt_builder_class.return_value = mock_prompt_builder_instance

        mock_system_message = ChatMessage(
            role="system", content="Discusser system prompt"
        )
        pb = mock_prompt_builder_instance
        pb.build_discusser_system_message.return_value = mock_system_message

        # Mock successful API response
        mock_api_instance.get_completion.return_value = (
            '{"private_thoughts":"Analysis","discussion_text":"Comment"}'
        )
        mock_parse.return_value = {
            "private_thoughts": "Analysis",
            "discussion_text": "Comment",
        }

        # Create player and discuss
        player = LLMPlayer("TestPlayer", model_config)
        player.discuss(proposal, game_state, rules)

        # Verify PromptBuilder.build_discusser_system_message called correctly
        call = mock_prompt_builder_instance.build_discusser_system_message
        call.assert_called_once_with(
            proposal=proposal,
            rules=rules,
            game_state=game_state,
            player_name="TestPlayer",
            personality="friendly",
        )


class TestLLMPlayerPropose:
    """Tests for LLMPlayer.propose() method."""

    @patch("src.nomic_engine.players.llm_player.PromptBuilder")
    @patch("src.nomic_engine.players.llm_player.ApiClient")
    @patch("src.nomic_engine.players.llm_player.parse_proposal_response")
    def test_propose_success_first_try(
        self,
        mock_parse,
        mock_api_client_class,
        mock_prompt_builder_class,
        model_config,
        game_state,
        rules,
    ):
        """Test successful proposal on the first attempt."""
        # Setup mocks
        mock_api_instance = MagicMock()
        mock_api_client_class.return_value = mock_api_instance

        mock_prompt_builder_instance = MagicMock()
        mock_prompt_builder_class.return_value = mock_prompt_builder_instance

        # Mock the prompt builder to return a single system ChatMessage
        mock_system_message = ChatMessage(
            role="system", content="Proposer system prompt"
        )
        pb = mock_prompt_builder_instance
        pb.build_proposer_system_message.return_value = mock_system_message

        # Mock the API client to return valid JSON
        valid_json_response = """{
            "private_thoughts": "Strategic analysis here",
            "type": "Add",
            "target_rule_id": null,
            "new_text": "New rule text for testing",
            "rationale": "This is good for the game"
        }"""
        mock_api_instance.get_completion.return_value = valid_json_response

        # Mock the parser to return valid data
        mock_parse.return_value = {
            "private_thoughts": "Strategic analysis here",
            "type": "Add",
            "target_rule_id": None,
            "new_text": "New rule text for testing",
            "rationale": "This is good for the game",
        }

        # Create player and propose
        player = LLMPlayer("TestPlayer", model_config)
        proposal = player.propose(game_state, rules)

        # Assertions
        assert proposal.proposer_name == "TestPlayer"
        assert proposal.type == ProposalType.ADD
        assert proposal.target_rule_id is None
        assert proposal.new_text == "New rule text for testing"
        assert proposal.rationale == "This is good for the game"
        assert proposal.move_number == game_state.move_number

        # Verify API was called only once
        assert mock_api_instance.get_completion.call_count == 1

        # Verify parser was called only once
        assert mock_parse.call_count == 1
        mock_parse.assert_called_with(valid_json_response)

    @patch("src.nomic_engine.players.llm_player.PromptBuilder")
    @patch("src.nomic_engine.players.llm_player.ApiClient")
    @patch("src.nomic_engine.players.llm_player.parse_proposal_response")
    def test_propose_success_amend_type(
        self,
        mock_parse,
        mock_api_client_class,
        mock_prompt_builder_class,
        model_config,
        game_state,
        rules,
    ):
        """Test successful AMEND proposal."""
        # Setup mocks
        mock_api_instance = MagicMock()
        mock_api_client_class.return_value = mock_api_instance

        mock_prompt_builder_instance = MagicMock()
        mock_prompt_builder_class.return_value = mock_prompt_builder_instance

        mock_system_message = ChatMessage(
            role="system", content="Proposer system prompt"
        )
        pb = mock_prompt_builder_instance
        pb.build_proposer_system_message.return_value = mock_system_message

        mock_api_instance.get_completion.return_value = "valid json"

        mock_parse.return_value = {
            "private_thoughts": "Analysis",
            "type": "Amend",
            "target_rule_id": "201",
            "new_text": "Amended rule text",
            "rationale": "This improves the rule",
        }

        # Create player and propose
        player = LLMPlayer("TestPlayer", model_config)
        proposal = player.propose(game_state, rules)

        # Assertions
        assert proposal.type == ProposalType.AMEND
        assert proposal.target_rule_id == "201"
        assert proposal.new_text == "Amended rule text"

    @patch("src.nomic_engine.players.llm_player.PromptBuilder")
    @patch("src.nomic_engine.players.llm_player.ApiClient")
    @patch("src.nomic_engine.players.llm_player.parse_proposal_response")
    def test_propose_success_after_retry(
        self,
        mock_parse,
        mock_api_client_class,
        mock_prompt_builder_class,
        model_config,
        game_state,
        rules,
    ):
        """Test successful proposal after one retry."""
        # Setup mocks
        mock_api_instance = MagicMock()
        mock_api_client_class.return_value = mock_api_instance

        mock_prompt_builder_instance = MagicMock()
        mock_prompt_builder_class.return_value = mock_prompt_builder_instance

        mock_system_message = ChatMessage(
            role="system", content="Proposer system prompt"
        )
        pb = mock_prompt_builder_instance
        pb.build_proposer_system_message.return_value = mock_system_message

        # Mock the API client to return bad JSON first, then good JSON
        bad_json_response = "This is not valid JSON"
        good_json_response = '{"type": "Add", ...}'
        mock_api_instance.get_completion.side_effect = [
            bad_json_response,
            good_json_response,
        ]

        # Mock the parser: raise ValueError first, then return valid data
        mock_parse.side_effect = [
            ValueError("Response is not valid JSON. Error: ..."),
            {
                "private_thoughts": "Better analysis now",
                "type": "Add",
                "target_rule_id": None,
                "new_text": "Fixed rule text",
                "rationale": "Better rationale",
            },
        ]

        # Create player and propose
        player = LLMPlayer("TestPlayer", model_config)
        proposal = player.propose(game_state, rules)

        # Assertions
        assert proposal.proposer_name == "TestPlayer"
        assert proposal.type == ProposalType.ADD
        assert proposal.new_text == "Fixed rule text"

        # Verify API was called twice
        assert mock_api_instance.get_completion.call_count == 2

        # Verify parser was called twice
        assert mock_parse.call_count == 2

        # Verify history contains retry messages
        # system, assistant(bad), user(retry), then another call succeeds
        assert len(player.turn_history) >= 3

    @patch("src.nomic_engine.players.llm_player.PromptBuilder")
    @patch("src.nomic_engine.players.llm_player.ApiClient")
    @patch("src.nomic_engine.players.llm_player.parse_proposal_response")
    def test_propose_failure_max_retries_raises_runtime_error(
        self,
        mock_parse,
        mock_api_client_class,
        mock_prompt_builder_class,
        model_config,
        game_state,
        rules,
    ):
        """Test that player raises RuntimeError after exhausting retries."""
        # Setup mocks
        mock_api_instance = MagicMock()
        mock_api_client_class.return_value = mock_api_instance

        mock_prompt_builder_instance = MagicMock()
        mock_prompt_builder_class.return_value = mock_prompt_builder_instance

        mock_system_message = ChatMessage(
            role="system", content="Proposer system prompt"
        )
        pb = mock_prompt_builder_instance
        pb.build_proposer_system_message.return_value = mock_system_message

        # Mock the API client to always return bad JSON
        bad_json_response = "This is consistently bad JSON {{{{{{"
        mock_api_instance.get_completion.return_value = bad_json_response

        # Mock the parser to always raise ValueError
        mock_parse.side_effect = ValueError("Response is not valid JSON")

        # Create player and propose
        player = LLMPlayer("TestPlayer", model_config)

        # Should raise RuntimeError after exhausting retries
        with pytest.raises(RuntimeError) as exc_info:
            player.propose(game_state, rules)

        assert "LLM failed to generate a valid proposal" in str(exc_info.value)

        # Verify API was called MAX_PROPOSE_RETRIES times (2)
        assert (
            mock_api_instance.get_completion.call_count
            == player.tuning.max_propose_retries
        )

        # Verify parser was called MAX_PROPOSE_RETRIES times
        assert mock_parse.call_count == player.tuning.max_propose_retries

    @patch("src.nomic_engine.players.llm_player.PromptBuilder")
    @patch("src.nomic_engine.players.llm_player.ApiClient")
    def test_propose_api_error_then_success(
        self,
        mock_api_client_class,
        mock_prompt_builder_class,
        model_config,
        game_state,
        rules,
    ):
        """Test that player retries after API errors (None response)."""
        # Setup mocks
        mock_api_instance = MagicMock()
        mock_api_client_class.return_value = mock_api_instance

        mock_prompt_builder_instance = MagicMock()
        mock_prompt_builder_class.return_value = mock_prompt_builder_instance

        mock_system_message = ChatMessage(
            role="system", content="Proposer system prompt"
        )
        pb = mock_prompt_builder_instance
        pb.build_proposer_system_message.return_value = mock_system_message

        # Mock the API client: first returns None (API error), second succeeds
        good_json_response = """{
            "private_thoughts": "Analysis",
            "type": "Add",
            "target_rule_id": null,
            "new_text": "New rule",
            "rationale": "Reason"
        }"""
        mock_api_instance.get_completion.side_effect = [
            None,
            good_json_response,
        ]

        # Create player and propose
        player = LLMPlayer("TestPlayer", model_config)
        proposal = player.propose(game_state, rules)

        # Assertions
        assert proposal.proposer_name == "TestPlayer"
        assert proposal.type == ProposalType.ADD

        # Verify API was called twice
        assert mock_api_instance.get_completion.call_count == 2

    @patch("src.nomic_engine.players.llm_player.PromptBuilder")
    @patch("src.nomic_engine.players.llm_player.ApiClient")
    def test_propose_all_api_errors_raises_runtime_error(
        self,
        mock_api_client_class,
        mock_prompt_builder_class,
        model_config,
        game_state,
        rules,
    ):
        """Test that player raises RuntimeError when API consistently fails."""
        # Setup mocks
        mock_api_instance = MagicMock()
        mock_api_client_class.return_value = mock_api_instance

        mock_prompt_builder_instance = MagicMock()
        mock_prompt_builder_class.return_value = mock_prompt_builder_instance

        mock_system_message = ChatMessage(
            role="system", content="Proposer system prompt"
        )
        pb = mock_prompt_builder_instance
        pb.build_proposer_system_message.return_value = mock_system_message

        # Mock the API client to always return None (API error)
        mock_api_instance.get_completion.return_value = None

        # Create player and propose
        player = LLMPlayer("TestPlayer", model_config)

        # Should raise RuntimeError
        with pytest.raises(RuntimeError) as exc_info:
            player.propose(game_state, rules)

        assert "LLM failed to generate a valid proposal" in str(exc_info.value)

        # Verify API was called MAX_PROPOSE_RETRIES times
        assert (
            mock_api_instance.get_completion.call_count
            == player.tuning.max_propose_retries
        )

    @patch("src.nomic_engine.players.llm_player.PromptBuilder")
    @patch("src.nomic_engine.players.llm_player.ApiClient")
    @patch("src.nomic_engine.players.llm_player.parse_proposal_response")
    def test_propose_prompt_builder_called_correctly(
        self,
        mock_parse,
        mock_api_client_class,
        mock_prompt_builder_class,
        model_config,
        game_state,
        rules,
    ):
        """Test that PromptBuilder is called with correct arguments."""
        # Setup mocks
        mock_api_instance = MagicMock()
        mock_api_client_class.return_value = mock_api_instance

        mock_prompt_builder_instance = MagicMock()
        mock_prompt_builder_class.return_value = mock_prompt_builder_instance

        mock_system_message = ChatMessage(
            role="system", content="Proposer system prompt"
        )
        pb = mock_prompt_builder_instance
        pb.build_proposer_system_message.return_value = mock_system_message

        # Mock successful API response
        mock_api_instance.get_completion.return_value = (
            '{"type":"ADD","private_thoughts":"A","target_rule_id":null,'
            '"new_text":"text","rationale":"r"}'
        )
        mock_parse.return_value = {
            "type": "Add",
            "private_thoughts": "A",
            "target_rule_id": None,
            "new_text": "text",
            "rationale": "r",
        }

        # Create player and propose
        player = LLMPlayer("TestPlayer", model_config)
        player.propose(game_state, rules)

        # Verify PromptBuilder.build_proposer_system_message called correctly
        call = mock_prompt_builder_instance.build_proposer_system_message
        call.assert_called_once_with(
            rules=rules,
            game_state=game_state,
            player_name="TestPlayer",
            personality="friendly",
        )


class TestLLMPlayerRevise:
    """Tests for LLMPlayer.revise() method."""

    @patch("src.nomic_engine.players.llm_player.PromptBuilder")
    @patch("src.nomic_engine.players.llm_player.ApiClient")
    @patch("src.nomic_engine.players.llm_player.parse_revision_response")
    def test_revise_withdraw(
        self,
        mock_parse,
        mock_api_client_class,
        mock_prompt_builder_class,
        model_config,
        game_state,
        proposal,
        rules,
    ):
        """Test that revise returns None when action is WITHDRAW."""
        # Setup mocks
        mock_api_instance = MagicMock()
        mock_api_client_class.return_value = mock_api_instance

        mock_prompt_builder_instance = MagicMock()
        mock_prompt_builder_class.return_value = mock_prompt_builder_instance

        # Mock the prompt builder to return a single user ChatMessage
        mock_revision_instruction = ChatMessage(
            role="user", content="Revision instruction prompt"
        )
        pb = mock_prompt_builder_instance
        pb.build_revision_instruction.return_value = mock_revision_instruction

        mock_api_instance.get_completion.return_value = """{
            "private_thoughts": "Too much opposition, better to withdraw",
            "action": "WITHDRAW",
            "new_text": null,
            "rationale": null
        }"""

        mock_parse.return_value = {
            "private_thoughts": "Too much opposition, better to withdraw",
            "action": "WITHDRAW",
            "new_text": None,
            "rationale": None,
        }

        # Create player with initial history (from propose)
        player = LLMPlayer("TestPlayer", model_config)
        player.turn_history = [
            ChatMessage(role="system", content="Proposer system prompt"),
            ChatMessage(
                role="assistant", content="Original proposal response"
            ),
        ]

        discussions = [
            Discussion(player_name="Alice", text="I have concerns about this.")
        ]
        result = player.revise(proposal, discussions, game_state, rules)

        # Should return None for withdraw
        assert result is None

        # Verify API was called only once
        assert mock_api_instance.get_completion.call_count == 1

    @patch("src.nomic_engine.players.llm_player.PromptBuilder")
    @patch("src.nomic_engine.players.llm_player.ApiClient")
    @patch("src.nomic_engine.players.llm_player.parse_revision_response")
    def test_revise_keep(
        self,
        mock_parse,
        mock_api_client_class,
        mock_prompt_builder_class,
        model_config,
        game_state,
        proposal,
        rules,
    ):
        """Test that revise returns original proposal when action is KEEP."""
        # Setup mocks
        mock_api_instance = MagicMock()
        mock_api_client_class.return_value = mock_api_instance

        mock_prompt_builder_instance = MagicMock()
        mock_prompt_builder_class.return_value = mock_prompt_builder_instance

        mock_revision_instruction = ChatMessage(
            role="user", content="Revision instruction prompt"
        )
        pb = mock_prompt_builder_instance
        pb.build_revision_instruction.return_value = mock_revision_instruction

        mock_api_instance.get_completion.return_value = """{
            "private_thoughts": "Feedback is positive, keep as is",
            "action": "KEEP",
            "new_text": null,
            "rationale": null
        }"""

        mock_parse.return_value = {
            "private_thoughts": "Feedback is positive, keep as is",
            "action": "KEEP",
            "new_text": None,
            "rationale": None,
        }

        # Create player with initial history (from propose)
        player = LLMPlayer("TestPlayer", model_config)
        player.turn_history = [
            ChatMessage(role="system", content="Proposer system prompt"),
            ChatMessage(
                role="assistant", content="Original proposal response"
            ),
        ]

        discussions = [Discussion(player_name="Alice", text="I support this.")]
        result = player.revise(proposal, discussions, game_state, rules)

        # Should return a proposal with same fields but updated thoughts
        assert result is not None
        assert result.new_text == proposal.new_text
        assert result.rationale == proposal.rationale
        assert result.private_thoughts == "Feedback is positive, keep as is"

        # Verify API was called only once
        assert mock_api_instance.get_completion.call_count == 1

    @patch("src.nomic_engine.players.llm_player.PromptBuilder")
    @patch("src.nomic_engine.players.llm_player.ApiClient")
    @patch("src.nomic_engine.players.llm_player.parse_revision_response")
    def test_revise_modify(
        self,
        mock_parse,
        mock_api_client_class,
        mock_prompt_builder_class,
        model_config,
        game_state,
        proposal,
        rules,
    ):
        """Test revise returns a modified proposal when action is MODIFY."""
        # Setup mocks
        mock_api_instance = MagicMock()
        mock_api_client_class.return_value = mock_api_instance

        mock_prompt_builder_instance = MagicMock()
        mock_prompt_builder_class.return_value = mock_prompt_builder_instance

        mock_revision_instruction = ChatMessage(
            role="user", content="Revision instruction prompt"
        )
        pb = mock_prompt_builder_instance
        pb.build_revision_instruction.return_value = mock_revision_instruction

        mock_api_instance.get_completion.return_value = """{
            "private_thoughts": "Will address the concerns by modifying",
            "action": "MODIFY",
            "new_text": "Modified rule text",
            "rationale": "Improved rationale"
        }"""

        mock_parse.return_value = {
            "private_thoughts": "Will address the concerns by modifying",
            "action": "MODIFY",
            "new_text": "Modified rule text",
            "rationale": "Improved rationale",
        }

        # Create player with initial history (from propose)
        player = LLMPlayer("TestPlayer", model_config)
        player.turn_history = [
            ChatMessage(role="system", content="Proposer system prompt"),
            ChatMessage(
                role="assistant", content="Original proposal response"
            ),
        ]

        discussions = [
            Discussion(player_name="Alice", text="This could be better.")
        ]
        result = player.revise(proposal, discussions, game_state, rules)

        # Should return a new proposal object with updated values
        assert result is not proposal  # Different object
        assert result.new_text == "Modified rule text"
        assert result.rationale == "Improved rationale"
        # Other fields should be the same
        assert result.proposer_name == proposal.proposer_name
        assert result.type == proposal.type

        # Verify API was called only once
        assert mock_api_instance.get_completion.call_count == 1

    @patch("src.nomic_engine.players.llm_player.PromptBuilder")
    @patch("src.nomic_engine.players.llm_player.ApiClient")
    @patch("src.nomic_engine.players.llm_player.parse_revision_response")
    def test_revise_modify_only_text(
        self,
        mock_parse,
        mock_api_client_class,
        mock_prompt_builder_class,
        model_config,
        game_state,
        proposal,
        rules,
    ):
        """Test revise only updates text when only new_text is provided."""
        # Setup mocks
        mock_api_instance = MagicMock()
        mock_api_client_class.return_value = mock_api_instance

        mock_prompt_builder_instance = MagicMock()
        mock_prompt_builder_class.return_value = mock_prompt_builder_instance

        mock_revision_instruction = ChatMessage(
            role="user", content="Revision instruction prompt"
        )
        pb = mock_prompt_builder_instance
        pb.build_revision_instruction.return_value = mock_revision_instruction

        mock_api_instance.get_completion.return_value = "valid json"

        mock_parse.return_value = {
            "private_thoughts": "Only updating the text",
            "action": "MODIFY",
            "new_text": "Only text updated",
            "rationale": None,
        }

        # Create player with initial history (from propose)
        player = LLMPlayer("TestPlayer", model_config)
        player.turn_history = [
            ChatMessage(role="system", content="Proposer system prompt"),
            ChatMessage(
                role="assistant", content="Original proposal response"
            ),
        ]

        result = player.revise(proposal, [], game_state, rules)

        # Should update text but keep original rationale
        assert result is not proposal
        assert result.new_text == "Only text updated"
        assert result.rationale == proposal.rationale

    @patch("src.nomic_engine.players.llm_player.PromptBuilder")
    @patch("src.nomic_engine.players.llm_player.ApiClient")
    @patch("src.nomic_engine.players.llm_player.parse_revision_response")
    def test_revise_success_after_retry(
        self,
        mock_parse,
        mock_api_client_class,
        mock_prompt_builder_class,
        model_config,
        game_state,
        proposal,
        rules,
    ):
        """Test successful revise after one retry."""
        # Setup mocks
        mock_api_instance = MagicMock()
        mock_api_client_class.return_value = mock_api_instance

        mock_prompt_builder_instance = MagicMock()
        mock_prompt_builder_class.return_value = mock_prompt_builder_instance

        mock_revision_instruction = ChatMessage(
            role="user", content="Revision instruction prompt"
        )
        pb = mock_prompt_builder_instance
        pb.build_revision_instruction.return_value = mock_revision_instruction

        bad_json_response = "This is not valid JSON"
        good_json_response = """{
            "private_thoughts": "Fixed response",
            "action": "KEEP",
            "new_text": null,
            "rationale": null
        }"""
        mock_api_instance.get_completion.side_effect = [
            bad_json_response,
            good_json_response,
        ]

        mock_parse.side_effect = [
            ValueError("Response is not valid JSON. Error: ..."),
            {
                "private_thoughts": "Fixed response",
                "action": "KEEP",
                "new_text": None,
                "rationale": None,
            },
        ]

        # Create player with initial history (from propose)
        player = LLMPlayer("TestPlayer", model_config)
        player.turn_history = [
            ChatMessage(role="system", content="Proposer system prompt"),
            ChatMessage(
                role="assistant", content="Original proposal response"
            ),
        ]

        result = player.revise(proposal, [], game_state, rules)

        # Should return a proposal with same fields but updated thoughts
        assert result is not None
        assert result.new_text == proposal.new_text
        assert result.rationale == proposal.rationale
        assert result.private_thoughts == "Fixed response"

        # Verify API was called twice
        assert mock_api_instance.get_completion.call_count == 2

        # Verify retry message was included in history
        assert len(player.turn_history) >= 4

    @patch("src.nomic_engine.players.llm_player.PromptBuilder")
    @patch("src.nomic_engine.players.llm_player.ApiClient")
    @patch("src.nomic_engine.players.llm_player.parse_revision_response")
    def test_revise_failure_max_retries_returns_original(
        self,
        mock_parse,
        mock_api_client_class,
        mock_prompt_builder_class,
        model_config,
        game_state,
        proposal,
        rules,
    ):
        """Test player returns original proposal after exhausting retries."""
        # Setup mocks
        mock_api_instance = MagicMock()
        mock_api_client_class.return_value = mock_api_instance

        mock_prompt_builder_instance = MagicMock()
        mock_prompt_builder_class.return_value = mock_prompt_builder_instance

        mock_revision_instruction = ChatMessage(
            role="user", content="Revision instruction prompt"
        )
        pb = mock_prompt_builder_instance
        pb.build_revision_instruction.return_value = mock_revision_instruction

        bad_json_response = "This is consistently bad JSON {{{{{{"
        mock_api_instance.get_completion.return_value = bad_json_response

        mock_parse.side_effect = ValueError("Response is not valid JSON")

        # Create player with initial history (from propose)
        player = LLMPlayer("TestPlayer", model_config)
        player.turn_history = [
            ChatMessage(role="system", content="Proposer system prompt"),
            ChatMessage(
                role="assistant", content="Original proposal response"
            ),
        ]

        result = player.revise(proposal, [], game_state, rules)

        # Should return original proposal as fallback (KEEP)
        assert result is proposal

        # Verify API was called MAX_REVISE_RETRIES times
        assert (
            mock_api_instance.get_completion.call_count
            == player.tuning.max_revise_retries
        )

    @patch("src.nomic_engine.players.llm_player.PromptBuilder")
    @patch("src.nomic_engine.players.llm_player.ApiClient")
    def test_revise_all_api_errors_returns_original(
        self,
        mock_api_client_class,
        mock_prompt_builder_class,
        model_config,
        game_state,
        proposal,
        rules,
    ):
        """Test that player returns original proposal when API fails."""
        # Setup mocks
        mock_api_instance = MagicMock()
        mock_api_client_class.return_value = mock_api_instance

        mock_prompt_builder_instance = MagicMock()
        mock_prompt_builder_class.return_value = mock_prompt_builder_instance

        mock_revision_instruction = ChatMessage(
            role="user", content="Revision instruction prompt"
        )
        pb = mock_prompt_builder_instance
        pb.build_revision_instruction.return_value = mock_revision_instruction

        mock_api_instance.get_completion.return_value = None

        # Create player with initial history (from propose)
        player = LLMPlayer("TestPlayer", model_config)
        player.turn_history = [
            ChatMessage(role="system", content="Proposer system prompt"),
            ChatMessage(
                role="assistant", content="Original proposal response"
            ),
        ]

        result = player.revise(proposal, [], game_state, rules)

        # Should return original proposal as fallback
        assert result is proposal

        # Verify API was called MAX_REVISE_RETRIES times
        assert (
            mock_api_instance.get_completion.call_count
            == player.tuning.max_revise_retries
        )

    @patch("src.nomic_engine.players.llm_player.PromptBuilder")
    @patch("src.nomic_engine.players.llm_player.ApiClient")
    @patch("src.nomic_engine.players.llm_player.parse_revision_response")
    def test_revise_prompt_builder_called_correctly(
        self,
        mock_parse,
        mock_api_client_class,
        mock_prompt_builder_class,
        model_config,
        game_state,
        proposal,
        rules,
    ):
        """Test that PromptBuilder is called with correct arguments."""
        # Setup mocks
        mock_api_instance = MagicMock()
        mock_api_client_class.return_value = mock_api_instance

        mock_prompt_builder_instance = MagicMock()
        mock_prompt_builder_class.return_value = mock_prompt_builder_instance

        mock_revision_instruction = ChatMessage(
            role="user", content="Revision instruction prompt"
        )
        pb = mock_prompt_builder_instance
        pb.build_revision_instruction.return_value = mock_revision_instruction

        mock_api_instance.get_completion.return_value = (
            '{"private_thoughts":"A","action":"KEEP","new_text":null,'
            '"rationale":null}'
        )
        mock_parse.return_value = {
            "private_thoughts": "A",
            "action": "KEEP",
            "new_text": None,
            "rationale": None,
        }

        # Create player with initial history (from propose)
        player = LLMPlayer("TestPlayer", model_config)
        player.turn_history = [
            ChatMessage(role="system", content="Proposer system prompt"),
            ChatMessage(
                role="assistant", content="Original proposal response"
            ),
        ]

        discussions = [Discussion(player_name="Alice", text="Good proposal.")]
        player.revise(proposal, discussions, game_state, rules)

        # Verify PromptBuilder.build_revision_instruction called correctly
        call = mock_prompt_builder_instance.build_revision_instruction
        call.assert_called_once_with(discussions=discussions)


class TestLLMPlayerStatefulHistory:
    """Tests for stateful conversation history management."""

    @patch("src.nomic_engine.players.llm_player.PromptBuilder")
    @patch("src.nomic_engine.players.llm_player.ApiClient")
    @patch("src.nomic_engine.players.llm_player.parse_proposal_response")
    def test_propose_initializes_history(
        self,
        mock_parse,
        mock_api_client_class,
        mock_prompt_builder_class,
        model_config,
        game_state,
        rules,
    ):
        """Test propose() initializes turn_history with [System, Assistant]."""
        # Setup mocks
        mock_api_instance = MagicMock()
        mock_api_client_class.return_value = mock_api_instance

        mock_prompt_builder_instance = MagicMock()
        mock_prompt_builder_class.return_value = mock_prompt_builder_instance

        mock_system_message = ChatMessage(
            role="system", content="Proposer system prompt"
        )
        pb = mock_prompt_builder_instance
        pb.build_proposer_system_message.return_value = mock_system_message

        valid_response = """{
            "private_thoughts": "Analysis",
            "type": "Add",
            "target_rule_id": null,
            "new_text": "New rule",
            "rationale": "Reason"
        }"""
        mock_api_instance.get_completion.return_value = valid_response

        mock_parse.return_value = {
            "private_thoughts": "Analysis",
            "type": "Add",
            "target_rule_id": None,
            "new_text": "New rule",
            "rationale": "Reason",
        }

        # Create player
        player = LLMPlayer("TestPlayer", model_config)

        # Initially history should be empty
        assert player.turn_history == []

        # Call propose
        player.propose(game_state, rules)

        # After propose, history should have [System, Assistant]
        assert len(player.turn_history) == 2
        assert player.turn_history[0].role == "system"
        assert player.turn_history[0].content == "Proposer system prompt"
        assert player.turn_history[1].role == "assistant"
        assert player.turn_history[1].content == valid_response

    @patch("src.nomic_engine.players.llm_player.PromptBuilder")
    @patch("src.nomic_engine.players.llm_player.ApiClient")
    @patch("src.nomic_engine.players.llm_player.parse_revision_response")
    def test_revise_extends_history(
        self,
        mock_parse,
        mock_api_client_class,
        mock_prompt_builder_class,
        model_config,
        game_state,
        proposal,
        rules,
    ):
        """Test that revise() extends the existing history, not replaces it."""
        # Setup mocks
        mock_api_instance = MagicMock()
        mock_api_client_class.return_value = mock_api_instance

        mock_prompt_builder_instance = MagicMock()
        mock_prompt_builder_class.return_value = mock_prompt_builder_instance

        mock_revision_instruction = ChatMessage(
            role="user", content="Revision instruction with discussions"
        )
        pb = mock_prompt_builder_instance
        pb.build_revision_instruction.return_value = mock_revision_instruction

        revision_response = """{
            "private_thoughts": "I will keep my proposal",
            "action": "KEEP",
            "new_text": null,
            "rationale": null
        }"""
        mock_api_instance.get_completion.return_value = revision_response

        mock_parse.return_value = {
            "private_thoughts": "I will keep my proposal",
            "action": "KEEP",
            "new_text": None,
            "rationale": None,
        }

        # Create player and manually set up initial history (from propose)
        player = LLMPlayer("TestPlayer", model_config)
        initial_system = ChatMessage(
            role="system", content="Proposer system prompt"
        )
        initial_assistant = ChatMessage(
            role="assistant", content="Original proposal JSON response"
        )
        player.turn_history = [initial_system, initial_assistant]

        # Call revise
        discussions = [Discussion(player_name="Alice", text="Good proposal.")]
        player.revise(proposal, discussions, game_state, rules)

        # After revise, history should have grown:
        # [System, Assistant(prop), User(revision_inst), Assistant(rev)]
        assert len(player.turn_history) == 4
        assert player.turn_history[0].role == "system"
        assert player.turn_history[1].role == "assistant"
        assert player.turn_history[2].role == "user"
        assert (
            player.turn_history[2].content
            == "Revision instruction with discussions"
        )
        assert player.turn_history[3].role == "assistant"
        assert player.turn_history[3].content == revision_response

    @patch("src.nomic_engine.players.llm_player.PromptBuilder")
    @patch("src.nomic_engine.players.llm_player.ApiClient")
    @patch("src.nomic_engine.players.llm_player.parse_vote_response")
    def test_vote_extends_history(
        self,
        mock_parse,
        mock_api_client_class,
        mock_prompt_builder_class,
        model_config,
        game_state,
        proposal,
        rules,
    ):
        """Test that vote() extends the existing history, not replaces it."""
        # Setup mocks
        mock_api_instance = MagicMock()
        mock_api_client_class.return_value = mock_api_instance

        mock_prompt_builder_instance = MagicMock()
        mock_prompt_builder_class.return_value = mock_prompt_builder_instance

        mock_vote_instruction = ChatMessage(
            role="user", content="Vote instruction with proposal"
        )
        mock_prompt_builder_instance.build_vote_instruction.return_value = (
            mock_vote_instruction
        )

        vote_response = """{
            "private_thoughts": "I will vote yes",
            "public_reason": "Good proposal",
            "vote": "YES"
        }"""
        mock_api_instance.get_completion.return_value = vote_response

        mock_parse.return_value = {
            "private_thoughts": "I will vote yes",
            "public_reason": "Good proposal",
            "vote": "YES",
        }

        # Create player and manually set up initial history (from discuss)
        player = LLMPlayer("TestPlayer", model_config)
        initial_system = ChatMessage(
            role="system", content="Discusser system prompt"
        )
        initial_assistant = ChatMessage(
            role="assistant", content="Discussion JSON response"
        )
        player.turn_history = [initial_system, initial_assistant]

        # Call vote
        player.vote(proposal, game_state, rules)

        # After vote, history should have grown:
        # [System, Assistant(discuss), User(vote_instruction), Assistant(vote)]
        assert len(player.turn_history) == 4
        assert player.turn_history[0].role == "system"
        assert player.turn_history[1].role == "assistant"
        assert player.turn_history[2].role == "user"
        assert (
            player.turn_history[2].content == "Vote instruction with proposal"
        )
        assert player.turn_history[3].role == "assistant"
        assert player.turn_history[3].content == vote_response

    @patch("src.nomic_engine.players.llm_player.PromptBuilder")
    @patch("src.nomic_engine.players.llm_player.ApiClient")
    @patch("src.nomic_engine.players.llm_player.parse_discussion_response")
    def test_discuss_initializes_history(
        self,
        mock_parse,
        mock_api_client_class,
        mock_prompt_builder_class,
        model_config,
        game_state,
        proposal,
        rules,
    ):
        """Test discuss() initializes turn_history with [System, Assistant]."""
        # Setup mocks
        mock_api_instance = MagicMock()
        mock_api_client_class.return_value = mock_api_instance

        mock_prompt_builder_instance = MagicMock()
        mock_prompt_builder_class.return_value = mock_prompt_builder_instance

        mock_system_message = ChatMessage(
            role="system", content="Discusser system prompt"
        )
        pb = mock_prompt_builder_instance
        pb.build_discusser_system_message.return_value = mock_system_message

        valid_response = """{
            "private_thoughts": "Analysis",
            "discussion_text": "I support this"
        }"""
        mock_api_instance.get_completion.return_value = valid_response

        mock_parse.return_value = {
            "private_thoughts": "Analysis",
            "discussion_text": "I support this",
        }

        # Create player with existing history (should be reset)
        player = LLMPlayer("TestPlayer", model_config)
        player.turn_history = [
            ChatMessage(role="system", content="Old history"),
            ChatMessage(role="assistant", content="Old response"),
        ]

        # Call discuss
        player.discuss(proposal, game_state, rules)

        # After discuss, history should be reset to [System, Assistant]
        assert len(player.turn_history) == 2
        assert player.turn_history[0].role == "system"
        assert player.turn_history[0].content == "Discusser system prompt"
        assert player.turn_history[1].role == "assistant"
        assert player.turn_history[1].content == valid_response

    @patch("src.nomic_engine.players.llm_player.PromptBuilder")
    @patch("src.nomic_engine.players.llm_player.ApiClient")
    @patch("src.nomic_engine.players.llm_player.parse_proposal_response")
    def test_propose_resets_existing_history(
        self,
        mock_parse,
        mock_api_client_class,
        mock_prompt_builder_class,
        model_config,
        game_state,
        rules,
    ):
        """Test that propose() resets any existing history."""
        # Setup mocks
        mock_api_instance = MagicMock()
        mock_api_client_class.return_value = mock_api_instance

        mock_prompt_builder_instance = MagicMock()
        mock_prompt_builder_class.return_value = mock_prompt_builder_instance

        mock_system_message = ChatMessage(
            role="system", content="New proposer system prompt"
        )
        pb = mock_prompt_builder_instance
        pb.build_proposer_system_message.return_value = mock_system_message

        mock_api_instance.get_completion.return_value = '{"type": "Add", ...}'
        mock_parse.return_value = {
            "private_thoughts": "Analysis",
            "type": "Add",
            "target_rule_id": None,
            "new_text": "New rule",
            "rationale": "Reason",
        }

        # Create player with existing history (should be reset)
        player = LLMPlayer("TestPlayer", model_config)
        player.turn_history = [
            ChatMessage(role="system", content="Old history"),
            ChatMessage(role="assistant", content="Old response"),
            ChatMessage(role="user", content="Old user message"),
        ]

        # Call propose
        player.propose(game_state, rules)

        # After propose, old history should be gone, replaced with new
        assert len(player.turn_history) == 2
        assert player.turn_history[0].role == "system"
        assert player.turn_history[0].content == "New proposer system prompt"
