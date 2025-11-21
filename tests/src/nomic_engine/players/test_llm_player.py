"""
Unit tests for LLMPlayer voting functionality with retry logic.
"""

from unittest.mock import MagicMock, patch

import pytest

from src.nomic_engine.data_models import (
    ChatMessage,
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
        turn_order=["Alice", "Bob"],
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

        # Mock the prompt builder to return messages
        mock_messages = [
            ChatMessage(role="system", content="System prompt"),
            ChatMessage(role="user", content="User prompt"),
        ]
        mock_prompt_builder_instance.build_vote_messages.return_value = (
            mock_messages
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

        # Create player and vote
        player = LLMPlayer("TestPlayer", model_config)
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

        # Mock the prompt builder to return initial messages
        mock_messages = [
            ChatMessage(role="system", content="System prompt"),
            ChatMessage(role="user", content="User prompt"),
        ]
        mock_prompt_builder_instance.build_vote_messages.return_value = (
            mock_messages
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

        # Create player and vote
        player = LLMPlayer("TestPlayer", model_config)
        vote = player.vote(proposal, game_state, rules)

        # Assertions
        assert vote.player_name == "TestPlayer"
        assert vote.vote == "NO"
        assert vote.reason == "I reconsider my position"

        # Verify API was called twice
        assert mock_api_instance.get_completion.call_count == 2

        # Verify parser was called twice
        assert mock_parse.call_count == 2

        # Verify that the second API call included the error feedback
        second_call_messages = mock_api_instance.get_completion.call_args_list[
            1
        ][0][0]
        # system, user, assistant (bad), user (retry)
        assert len(second_call_messages) == 4
        assert second_call_messages[2].role == "assistant"
        assert second_call_messages[2].content == bad_json_response
        assert second_call_messages[3].role == "user"
        # The retry template should be in the last message
        assert "FINAL attempt" in second_call_messages[3].content

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

        # Mock the prompt builder to return messages
        mock_messages = [
            ChatMessage(role="system", content="System prompt"),
            ChatMessage(role="user", content="User prompt"),
        ]
        mock_prompt_builder_instance.build_vote_messages.return_value = (
            mock_messages
        )

        # Mock the API client to always return bad JSON
        bad_json_response = "This is consistently bad JSON {{{{{{"
        mock_api_instance.get_completion.return_value = bad_json_response

        # Mock the parser to always raise ValueError
        mock_parse.side_effect = ValueError("Response is not valid JSON")

        # Create player and vote
        player = LLMPlayer("TestPlayer", model_config)
        vote = player.vote(proposal, game_state, rules)

        # Assertions - should return ABSTAIN with error message
        assert vote.player_name == "TestPlayer"
        assert vote.vote == "ABSTAIN"
        assert vote.reason == "LLM Error: Failed to generate valid vote."

        # Verify API was called MAX_VOTE_RETRIES times (2)
        assert (
            mock_api_instance.get_completion.call_count
            == LLMPlayer.MAX_VOTE_RETRIES
        )

        # Verify parser was called MAX_VOTE_RETRIES times
        assert mock_parse.call_count == LLMPlayer.MAX_VOTE_RETRIES

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

        # Mock the prompt builder to return messages
        mock_messages = [
            ChatMessage(role="system", content="System prompt"),
            ChatMessage(role="user", content="User prompt"),
        ]
        mock_prompt_builder_instance.build_vote_messages.return_value = (
            mock_messages
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

        # Create player and vote
        player = LLMPlayer("TestPlayer", model_config)
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

        # Mock the prompt builder to return messages
        mock_messages = [
            ChatMessage(role="system", content="System prompt"),
            ChatMessage(role="user", content="User prompt"),
        ]
        mock_prompt_builder_instance.build_vote_messages.return_value = (
            mock_messages
        )

        # Mock the API client to always return None (API error)
        mock_api_instance.get_completion.return_value = None

        # Create player and vote
        player = LLMPlayer("TestPlayer", model_config)
        vote = player.vote(proposal, game_state, rules)

        # Assertions - should return ABSTAIN with error message
        assert vote.player_name == "TestPlayer"
        assert vote.vote == "ABSTAIN"
        assert vote.reason == "LLM Error: Failed to generate valid vote."

        # Verify API was called MAX_VOTE_RETRIES times
        assert (
            mock_api_instance.get_completion.call_count
            == LLMPlayer.MAX_VOTE_RETRIES
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

        # Mock the prompt builder to return messages
        mock_messages = [
            ChatMessage(role="system", content="System prompt"),
            ChatMessage(role="user", content="User prompt"),
        ]
        mock_prompt_builder_instance.build_vote_messages.return_value = (
            mock_messages
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

        # Create player and vote
        player = LLMPlayer("TestPlayer", model_config)
        player.vote(proposal, game_state, rules)

        # Verify PromptBuilder.build_vote_messages was called with correct args
        mock_prompt_builder_instance.build_vote_messages.assert_called_once_with(
            proposal=proposal,
            rules=rules,
            game_state=game_state,
            discussions=[],  # Currently empty
            player_name="TestPlayer",
        )
