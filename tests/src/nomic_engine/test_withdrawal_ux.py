"""
Tests for Withdrawal UX Improvements (Sprint 29, Task 4).

Covers:
- Sub-task A: WITHDRAWAL_RETRY_TEMPLATE content and HumanPlayer display
- Sub-task B: retain_discusser_history_on_retry config flag and
  LLMPlayer/GameLoop behaviour
"""

from unittest.mock import MagicMock, Mock, patch

import pytest

from src.nomic_engine.data_models import (
    ChatMessage,
    Discussion,
    GameConfig,
    GameState,
    ModelDefinition,
    Proposal,
    ProposalType,
    Rule,
    RuleStatus,
    WithdrawalPolicy,
)
from src.nomic_engine.llm import prompts
from src.nomic_engine.players.human_player import HumanPlayer
from src.nomic_engine.players.llm_player import LLMPlayer

# =====================================================================
# Fixtures
# =====================================================================


@pytest.fixture
def model_config() -> ModelDefinition:
    return ModelDefinition(
        id="test-model",
        provider="local",
        api_model_id="http://localhost:11434",
        env_key_name=None,
    )


@pytest.fixture
def game_state() -> GameState:
    return GameState(
        scores={"Alice": 0, "Bob": 0},
        current_player_name="Alice",
        move_number=1,
        turn_order=["Alice", "Bob"],
        next_proposal_id=301,
    )


@pytest.fixture
def proposal() -> Proposal:
    return Proposal(
        proposer_name="Alice",
        move_number=1,
        type=ProposalType.ADD,
        proposal_id="301",
        new_text="New rule text",
        rationale="Good idea",
    )


@pytest.fixture
def rules() -> list[Rule]:
    return [
        Rule(
            rule_id="101",
            text="Rule text",
            status=RuleStatus.IMMUTABLE,
        )
    ]


# =====================================================================
# Sub-task A: WITHDRAWAL_RETRY_TEMPLATE
# =====================================================================


class TestWithdrawalRetryTemplate:
    """Tests for the updated WITHDRAWAL_RETRY_TEMPLATE prompt text."""

    def test_template_contains_attempt_placeholders(self) -> None:
        """Template must include both attempt-count placeholders."""
        assert "{withdrawal_attempt}" in prompts.WITHDRAWAL_RETRY_TEMPLATE
        assert "{max_withdrawal_retries}" in prompts.WITHDRAWAL_RETRY_TEMPLATE

    def test_template_formats_attempt_numbers(self) -> None:
        """Formatted template must render attempt numbers."""
        rendered = prompts.WITHDRAWAL_RETRY_TEMPLATE.format(
            withdrawal_attempt=2,
            max_withdrawal_retries=3,
        )
        assert "2" in rendered
        assert "3" in rendered

    def test_template_mentions_withdraw_action(self) -> None:
        """Template must mention WITHDRAW for type/rule-ID changes."""
        rendered = prompts.WITHDRAWAL_RETRY_TEMPLATE.format(
            withdrawal_attempt=1,
            max_withdrawal_retries=2,
        )
        # Must guide the LLM to use WITHDRAW not MODIFY for type/rule changes
        assert "WITHDRAW" in rendered

    def test_template_mentions_proposal_type_guidance(self) -> None:
        """Template must mention proposal type or target rule guidance."""
        rendered = prompts.WITHDRAWAL_RETRY_TEMPLATE.format(
            withdrawal_attempt=1,
            max_withdrawal_retries=2,
        )
        # Must mention that type or rule ID changes require WITHDRAW
        lower = rendered.lower()
        assert "type" in lower or "target" in lower or "rule" in lower

    def test_template_mentions_modify_action(self) -> None:
        """Template must mention MODIFY so the LLM understands the contrast."""
        rendered = prompts.WITHDRAWAL_RETRY_TEMPLATE.format(
            withdrawal_attempt=1,
            max_withdrawal_retries=2,
        )
        assert "MODIFY" in rendered


# =====================================================================
# Sub-task A: HumanPlayer.propose() withdrawal display
# =====================================================================


class TestHumanPlayerProposeWithdrawalDisplay:
    """Tests for HumanPlayer.propose() displaying withdrawal info."""

    def test_propose_continue_turn_prints_attempt_info(
        self,
        game_state: GameState,
        rules: list[Rule],
        capsys: pytest.CaptureFixture,
    ) -> None:
        """continue_turn=True must print attempt number and max retries."""
        player = HumanPlayer("Alice")
        with patch("builtins.input") as mock_input:
            mock_input.side_effect = [
                "A",  # proposal type: ADD
                "New rule text",  # new text
                "My rationale",  # rationale
            ]
            player.propose(
                game_state,
                rules,
                continue_turn=True,
                withdrawal_attempt=1,
                max_withdrawal_retries=2,
            )

        captured = capsys.readouterr()
        assert "1" in captured.out
        assert "2" in captured.out

    def test_propose_continue_turn_prints_withdraw_guidance(
        self,
        game_state: GameState,
        rules: list[Rule],
        capsys: pytest.CaptureFixture,
    ) -> None:
        """continue_turn=True must print WITHDRAW guidance for type/rule."""
        player = HumanPlayer("Alice")
        with patch("builtins.input") as mock_input:
            mock_input.side_effect = [
                "A",
                "text",
                "rationale",
            ]
            player.propose(
                game_state,
                rules,
                continue_turn=True,
                withdrawal_attempt=1,
                max_withdrawal_retries=2,
            )

        captured = capsys.readouterr()
        # Must mention WITHDRAW and type/rule changes
        assert "WITHDRAW" in captured.out or "withdraw" in captured.out.lower()

    def test_propose_normal_turn_no_withdrawal_info(
        self,
        game_state: GameState,
        rules: list[Rule],
        capsys: pytest.CaptureFixture,
    ) -> None:
        """continue_turn=False must not print withdrawal info."""
        player = HumanPlayer("Alice")
        with patch("builtins.input") as mock_input:
            mock_input.side_effect = [
                "A",
                "text",
                "rationale",
            ]
            player.propose(game_state, rules, continue_turn=False)

        captured = capsys.readouterr()
        assert "withdrawal" not in captured.out.lower()
        assert "attempt" not in captured.out.lower()

    def test_propose_returns_valid_proposal(
        self, game_state: GameState, rules: list[Rule]
    ) -> None:
        """propose() must still return a valid Proposal with new params."""
        player = HumanPlayer("Alice")
        with patch("builtins.input") as mock_input:
            mock_input.side_effect = [
                "A",
                "Some new rule text",
                "rationale",
            ]
            result = player.propose(
                game_state,
                rules,
                continue_turn=True,
                withdrawal_attempt=2,
                max_withdrawal_retries=3,
            )

        assert result.proposer_name == "Alice"
        assert result.type == ProposalType.ADD
        assert result.new_text == "Some new rule text"


# =====================================================================
# Sub-task A: HumanPlayer.discuss() interface consistency
# =====================================================================


class TestHumanPlayerDiscussContinueTurn:
    """Tests for HumanPlayer.discuss() accepting continue_turn parameter."""

    def test_discuss_accepts_continue_turn_false(
        self,
        proposal: Proposal,
        game_state: GameState,
        rules: list[Rule],
    ) -> None:
        """discuss() must accept continue_turn=False without error."""
        player = HumanPlayer("Bob")
        with patch("builtins.input", return_value="My thoughts"):
            result = player.discuss(
                proposal, game_state, rules, continue_turn=False
            )
        assert result.player_name == "Bob"
        assert result.text == "My thoughts"

    def test_discuss_accepts_continue_turn_true(
        self,
        proposal: Proposal,
        game_state: GameState,
        rules: list[Rule],
    ) -> None:
        """discuss() must accept continue_turn=True without error."""
        player = HumanPlayer("Bob")
        with patch("builtins.input", return_value="Updated thoughts"):
            result = player.discuss(
                proposal, game_state, rules, continue_turn=True
            )
        assert result.player_name == "Bob"
        assert result.text == "Updated thoughts"

    def test_discuss_continue_turn_has_no_side_effect(
        self,
        proposal: Proposal,
        game_state: GameState,
        rules: list[Rule],
    ) -> None:
        """For human players, continue_turn must not change behaviour."""
        player = HumanPlayer("Bob")
        with patch("builtins.input", return_value="Same text"):
            r1 = player.discuss(
                proposal, game_state, rules, continue_turn=False
            )
        with patch("builtins.input", return_value="Same text"):
            r2 = player.discuss(
                proposal, game_state, rules, continue_turn=True
            )
        assert r1.text == r2.text


# =====================================================================
# Sub-task B: GameConfig.retain_discusser_history_on_retry
# =====================================================================


class TestGameConfigRetainDiscusserHistory:
    """Tests for retain_discusser_history_on_retry field in GameConfig."""

    def test_default_is_true(self) -> None:
        """retain_discusser_history_on_retry must default to True."""
        config = GameConfig(
            players=[],
            withdrawal_policy=WithdrawalPolicy.RETRY,
        )
        assert config.retain_discusser_history_on_retry is True

    def test_can_be_set_to_false(self) -> None:
        """retain_discusser_history_on_retry can be set to False."""
        config = GameConfig(
            players=[],
            withdrawal_policy=WithdrawalPolicy.RETRY,
            retain_discusser_history_on_retry=False,
        )
        assert config.retain_discusser_history_on_retry is False

    def test_existing_config_loads_without_field(self) -> None:
        """Configs without the field should load with default=True."""
        # Simulate loading a config dict that lacks the new field
        data = {
            "players": [],
            "withdrawal_policy": "retry",
        }
        config = GameConfig(**data)
        assert config.retain_discusser_history_on_retry is True

    def test_field_appears_in_model_dump(self) -> None:
        """The new field must be serialised by model_dump()."""
        config = GameConfig(players=[])
        dumped = config.model_dump()
        assert "retain_discusser_history_on_retry" in dumped
        assert dumped["retain_discusser_history_on_retry"] is True


# =====================================================================
# Sub-task B: LLMPlayer.discuss() continue_turn behaviour
# =====================================================================


class TestLLMPlayerDiscussContinueTurn:
    """Tests for LLMPlayer.discuss() history management with continue_turn."""

    @patch("src.nomic_engine.players.llm_player.PromptBuilder")
    @patch("src.nomic_engine.players.llm_player.ApiClient")
    @patch("src.nomic_engine.players.llm_player.parse_discussion_response")
    def test_discuss_default_resets_history(
        self,
        mock_parse: MagicMock,
        mock_api_client_class: MagicMock,
        mock_prompt_builder_class: MagicMock,
        model_config: ModelDefinition,
        proposal: Proposal,
        game_state: GameState,
        rules: list[Rule],
    ) -> None:
        """Default discuss() (continue_turn=False) resets history."""
        mock_api = mock_api_client_class.return_value
        mock_pb = mock_prompt_builder_class.return_value
        mock_pb.build_discusser_system_message.return_value = ChatMessage(
            role="system", content="New system msg"
        )
        mock_api.get_completion.return_value = '{"x":"y"}'
        mock_parse.return_value = {
            "private_thoughts": "t",
            "discussion_text": "text",
        }

        player = LLMPlayer("Bob", model_config)
        # Populate existing history
        player.turn_history = [
            ChatMessage(role="system", content="Old system"),
            ChatMessage(role="assistant", content="Old response"),
            ChatMessage(role="user", content="Old user msg"),
        ]

        player.discuss(proposal, game_state, rules)

        # History should have been reset to [system, assistant]
        assert len(player.turn_history) == 2
        assert player.turn_history[0].content == "New system msg"

    @patch("src.nomic_engine.players.llm_player.PromptBuilder")
    @patch("src.nomic_engine.players.llm_player.ApiClient")
    @patch("src.nomic_engine.players.llm_player.parse_discussion_response")
    def test_discuss_continue_turn_preserves_history(
        self,
        mock_parse: MagicMock,
        mock_api_client_class: MagicMock,
        mock_prompt_builder_class: MagicMock,
        model_config: ModelDefinition,
        proposal: Proposal,
        game_state: GameState,
        rules: list[Rule],
    ) -> None:
        """discuss(continue_turn=True) must preserve existing history."""
        mock_api = mock_api_client_class.return_value
        mock_pb = mock_prompt_builder_class.return_value
        mock_pb.build_discusser_system_message.return_value = ChatMessage(
            role="system", content="New system msg"
        )
        mock_api.get_completion.return_value = '{"x":"y"}'
        mock_parse.return_value = {
            "private_thoughts": "t",
            "discussion_text": "retained context",
        }

        player = LLMPlayer("Bob", model_config)
        # Populate existing history (e.g., from a previous discussion round)
        prior_history = [
            ChatMessage(role="system", content="Prior system"),
            ChatMessage(role="assistant", content="Prior discussion"),
        ]
        player.turn_history = list(prior_history)

        player.discuss(proposal, game_state, rules, continue_turn=True)

        # The prior history should still be at the start
        assert player.turn_history[0].content == "Prior system"
        assert player.turn_history[1].content == "Prior discussion"
        # History grew (assistant response appended)
        assert len(player.turn_history) > len(prior_history)

    @patch("src.nomic_engine.players.llm_player.PromptBuilder")
    @patch("src.nomic_engine.players.llm_player.ApiClient")
    @patch("src.nomic_engine.players.llm_player.parse_discussion_response")
    def test_discuss_continue_turn_empty_history_falls_back_to_reset(
        self,
        mock_parse: MagicMock,
        mock_api_client_class: MagicMock,
        mock_prompt_builder_class: MagicMock,
        model_config: ModelDefinition,
        proposal: Proposal,
        game_state: GameState,
        rules: list[Rule],
    ) -> None:
        """continue_turn=True with empty history falls back to reset."""
        mock_api = mock_api_client_class.return_value
        mock_pb = mock_prompt_builder_class.return_value
        mock_pb.build_discusser_system_message.return_value = ChatMessage(
            role="system", content="Fresh system"
        )
        mock_api.get_completion.return_value = '{"x":"y"}'
        mock_parse.return_value = {
            "private_thoughts": "t",
            "discussion_text": "ok",
        }

        player = LLMPlayer("Bob", model_config)
        # History is empty despite continue_turn=True (defensive path)
        assert player.turn_history == []

        player.discuss(proposal, game_state, rules, continue_turn=True)

        # Should have been initialised with the system message
        assert player.turn_history[0].role == "system"
        assert player.turn_history[0].content == "Fresh system"

    @patch("src.nomic_engine.players.llm_player.PromptBuilder")
    @patch("src.nomic_engine.players.llm_player.ApiClient")
    @patch("src.nomic_engine.players.llm_player.parse_discussion_response")
    def test_discuss_false_produces_identical_behavior_to_original(
        self,
        mock_parse: MagicMock,
        mock_api_client_class: MagicMock,
        mock_prompt_builder_class: MagicMock,
        model_config: ModelDefinition,
        proposal: Proposal,
        game_state: GameState,
        rules: list[Rule],
    ) -> None:
        """discuss(continue_turn=False) must behave identically to old code."""
        mock_api = mock_api_client_class.return_value
        mock_pb = mock_prompt_builder_class.return_value
        mock_pb.build_discusser_system_message.return_value = ChatMessage(
            role="system", content="System"
        )
        mock_api.get_completion.return_value = '{"x":"y"}'
        mock_parse.return_value = {
            "private_thoughts": "t",
            "discussion_text": "response",
        }

        player = LLMPlayer("Bob", model_config)
        player.turn_history = [
            ChatMessage(role="system", content="Old"),
            ChatMessage(role="assistant", content="Old resp"),
        ]

        result = player.discuss(
            proposal, game_state, rules, continue_turn=False
        )

        # History should have been reset (old code behaviour)
        assert player.turn_history[0].content == "System"
        assert result.text == "response"
        assert result.player_name == "Bob"


# =====================================================================
# Sub-task B: GameLoop._collect_discussions() with is_retry flag
# =====================================================================


class TestCollectDiscussionsRetainHistory:
    """Tests for _collect_discussions() continue_turn propagation."""

    def _make_game_loop(
        self,
        retain_flag: bool = True,
        withdrawal_policy: WithdrawalPolicy = WithdrawalPolicy.RETRY,
    ):
        """Helper to build a minimal GameLoop with mocked dependencies."""
        from src.nomic_engine.core.game_loop import GameLoop

        game_state = GameState(
            scores={"Alice": 0, "Bob": 0},
            current_player_name="Alice",
            move_number=1,
            turn_order=["Alice", "Bob"],
            next_proposal_id=301,
        )
        rules = [Rule(rule_id="101", text="r", status=RuleStatus.IMMUTABLE)]

        rules_manager = Mock()
        rules_manager.rules = rules

        game_config = GameConfig(
            players=[],
            withdrawal_policy=withdrawal_policy,
            retain_discusser_history_on_retry=retain_flag,
        )

        manager = Mock()
        manager.game_state = game_state
        manager.rules_manager = rules_manager
        manager.game_config = game_config
        manager.logger = Mock()
        manager.save_game_state = Mock()

        # Mock players
        alice = Mock()
        alice.player_name = "Alice"
        bob = Mock()
        bob.player_name = "Bob"
        bob.discuss.return_value = Discussion(
            player_name="Bob", text="Bob's comment"
        )

        game_loop = GameLoop.__new__(GameLoop)
        game_loop.game_manager = manager
        game_loop.players = [alice, bob]
        game_loop.judge = Mock()

        return game_loop, alice, bob

    def _make_proposal(self, proposer: str = "Alice") -> Proposal:
        return Proposal(
            proposer_name=proposer,
            move_number=1,
            type=ProposalType.ADD,
            proposal_id="301",
            new_text="New rule",
            rationale="Because",
        )

    def test_first_attempt_passes_continue_turn_false(self) -> None:
        """is_retry=False must pass continue_turn=False to non-proposers."""
        game_loop, _alice, bob = self._make_game_loop(retain_flag=True)
        proposal = self._make_proposal()

        game_loop._collect_discussions(
            proposal, game_loop.players, is_retry=False
        )

        bob.discuss.assert_called_once()
        call_kwargs = bob.discuss.call_args[1]
        assert call_kwargs["continue_turn"] is False

    def test_retry_with_flag_true_passes_continue_turn_true(self) -> None:
        """is_retry=True + retain=True must pass continue_turn=True."""
        game_loop, _alice, bob = self._make_game_loop(retain_flag=True)
        proposal = self._make_proposal()

        game_loop._collect_discussions(
            proposal, game_loop.players, is_retry=True
        )

        bob.discuss.assert_called_once()
        call_kwargs = bob.discuss.call_args[1]
        assert call_kwargs["continue_turn"] is True

    def test_retry_with_flag_false_passes_continue_turn_false(self) -> None:
        """is_retry=True + retain=False must pass continue_turn=False."""
        game_loop, _alice, bob = self._make_game_loop(retain_flag=False)
        proposal = self._make_proposal()

        game_loop._collect_discussions(
            proposal, game_loop.players, is_retry=True
        )

        bob.discuss.assert_called_once()
        call_kwargs = bob.discuss.call_args[1]
        assert call_kwargs["continue_turn"] is False

    def test_proposer_is_never_called_for_discussion(self) -> None:
        """Proposer (Alice) should not have discuss() called."""
        game_loop, alice, _bob = self._make_game_loop()
        proposal = self._make_proposal(proposer="Alice")

        game_loop._collect_discussions(
            proposal, game_loop.players, is_retry=True
        )

        alice.discuss.assert_not_called()

    def test_no_game_config_passes_continue_turn_false(self) -> None:
        """If game_config is None, continue_turn must default to False."""
        from src.nomic_engine.core.game_loop import GameLoop

        game_state = GameState(
            scores={"Alice": 0, "Bob": 0},
            current_player_name="Alice",
            move_number=1,
            turn_order=["Alice", "Bob"],
            next_proposal_id=301,
        )
        rules = [Rule(rule_id="101", text="r", status=RuleStatus.IMMUTABLE)]

        rules_manager = Mock()
        rules_manager.rules = rules

        manager = Mock()
        manager.game_state = game_state
        manager.rules_manager = rules_manager
        manager.game_config = None  # No config
        manager.logger = Mock()

        alice = Mock()
        alice.player_name = "Alice"
        bob = Mock()
        bob.player_name = "Bob"
        bob.discuss.return_value = Discussion(
            player_name="Bob", text="comment"
        )

        game_loop = GameLoop.__new__(GameLoop)
        game_loop.game_manager = manager
        game_loop.players = [alice, bob]
        game_loop.judge = Mock()

        proposal = Proposal(
            proposer_name="Alice",
            move_number=1,
            type=ProposalType.ADD,
            proposal_id="301",
            new_text="rule",
            rationale="why",
        )

        game_loop._collect_discussions(proposal, [alice, bob], is_retry=True)

        bob.discuss.assert_called_once()
        call_kwargs = bob.discuss.call_args[1]
        assert call_kwargs["continue_turn"] is False
