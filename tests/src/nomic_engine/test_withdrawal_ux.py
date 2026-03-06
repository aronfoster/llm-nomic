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
    CompletionResult,
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
# Sub-task A: HumanPlayer.begin_discussion_turn() and discuss()
# =====================================================================


class TestHumanPlayerDiscuss:
    """Tests for HumanPlayer.begin_discussion_turn() and discuss()."""

    def test_discuss_returns_valid_discussion(
        self,
        proposal: Proposal,
        game_state: GameState,
        rules: list[Rule],
    ) -> None:
        """discuss() must return a Discussion with the player's text."""
        player = HumanPlayer("Bob")
        with patch("builtins.input", return_value="My thoughts"):
            result = player.discuss(proposal, game_state, rules)
        assert result.player_name == "Bob"
        assert result.text == "My thoughts"

    def test_begin_discussion_turn_is_noop(
        self,
        proposal: Proposal,
        game_state: GameState,
        rules: list[Rule],
    ) -> None:
        """begin_discussion_turn() must complete without error or output."""
        player = HumanPlayer("Bob")
        # Should not raise and should produce no output
        player.begin_discussion_turn(proposal, game_state, rules)

    def test_begin_discussion_turn_followed_by_discuss(
        self,
        proposal: Proposal,
        game_state: GameState,
        rules: list[Rule],
    ) -> None:
        """Calling begin_discussion_turn() then discuss() must work."""
        player = HumanPlayer("Bob")
        player.begin_discussion_turn(proposal, game_state, rules)
        with patch("builtins.input", return_value="My comment"):
            result = player.discuss(proposal, game_state, rules)
        assert result.player_name == "Bob"
        assert result.text == "My comment"


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
# Sub-task B: LLMPlayer.begin_discussion_turn() and discuss()
# =====================================================================


class TestLLMPlayerBeginDiscussionTurn:
    """Tests for LLMPlayer.begin_discussion_turn() and discuss()."""

    @patch("src.nomic_engine.players.llm_player.PromptBuilder")
    @patch("src.nomic_engine.players.llm_player.create_api_client")
    def test_begin_discussion_turn_resets_history(
        self,
        mock_api_client_class: MagicMock,
        mock_prompt_builder_class: MagicMock,
        model_config: ModelDefinition,
        proposal: Proposal,
        game_state: GameState,
        rules: list[Rule],
    ) -> None:
        """begin_discussion_turn() must reset history to the new system msg."""
        mock_pb = mock_prompt_builder_class.return_value
        mock_pb.build_discusser_system_message.return_value = (
            ChatMessage(role="system", content="New system msg"),
            ChatMessage(role="user", content="New user msg"),
        )

        player = LLMPlayer("Bob", model_config)
        # Populate existing history to confirm it gets overwritten
        player.turn_history = [
            ChatMessage(role="system", content="Old system"),
            ChatMessage(role="assistant", content="Old response"),
        ]

        player.begin_discussion_turn(proposal, game_state, rules)

        assert len(player.turn_history) == 2
        assert player.turn_history[0].content == "New system msg"
        assert player.turn_history[1].content == "New user msg"

    @patch("src.nomic_engine.players.llm_player.PromptBuilder")
    @patch("src.nomic_engine.players.llm_player.create_api_client")
    @patch("src.nomic_engine.players.llm_player.parse_discussion_response")
    def test_discuss_does_not_reset_history(
        self,
        mock_parse: MagicMock,
        mock_api_client_class: MagicMock,
        mock_prompt_builder_class: MagicMock,
        model_config: ModelDefinition,
        proposal: Proposal,
        game_state: GameState,
        rules: list[Rule],
    ) -> None:
        """discuss() must not reset history — it uses whatever is in place."""
        mock_api = mock_api_client_class.return_value
        mock_pb = mock_prompt_builder_class.return_value
        mock_pb.build_discusser_system_message.return_value = (
            ChatMessage(role="system", content="Should not appear"),
            ChatMessage(role="user", content="Should not appear user"),
        )
        mock_api.get_completion.return_value = CompletionResult(
            text='{"x":"y"}', raw_response=None, client_latency_ms=0
        )
        mock_parse.return_value = {
            "private_thoughts": "t",
            "discussion_text": "my take",
        }

        player = LLMPlayer("Bob", model_config)
        # Seed history as begin_discussion_turn() would in normal usage
        prior_history = [
            ChatMessage(role="system", content="Prior system"),
            ChatMessage(role="assistant", content="Prior discussion"),
        ]
        player.turn_history = list(prior_history)

        player.discuss(proposal, game_state, rules)

        # First two entries must be unchanged (history not reset)
        assert player.turn_history[0].content == "Prior system"
        assert player.turn_history[1].content == "Prior discussion"
        # History grew by one (the new assistant response)
        assert len(player.turn_history) == len(prior_history) + 1

    @patch("src.nomic_engine.players.llm_player.PromptBuilder")
    @patch("src.nomic_engine.players.llm_player.create_api_client")
    @patch("src.nomic_engine.players.llm_player.parse_discussion_response")
    def test_begin_then_discuss_uses_new_context(
        self,
        mock_parse: MagicMock,
        mock_api_client_class: MagicMock,
        mock_prompt_builder_class: MagicMock,
        model_config: ModelDefinition,
        proposal: Proposal,
        game_state: GameState,
        rules: list[Rule],
    ) -> None:
        """begin_discussion_turn() followed by discuss() uses fresh context."""
        mock_api = mock_api_client_class.return_value
        mock_pb = mock_prompt_builder_class.return_value
        mock_pb.build_discusser_system_message.return_value = (
            ChatMessage(role="system", content="Fresh context"),
            ChatMessage(role="user", content="Fresh user context"),
        )
        mock_api.get_completion.return_value = CompletionResult(
            text='{"x":"y"}', raw_response=None, client_latency_ms=0
        )
        mock_parse.return_value = {
            "private_thoughts": "t",
            "discussion_text": "fresh take",
        }

        player = LLMPlayer("Bob", model_config)
        # begin_discussion_turn initialises history
        player.begin_discussion_turn(proposal, game_state, rules)
        assert player.turn_history[0].content == "Fresh context"

        result = player.discuss(proposal, game_state, rules)
        assert result.text == "fresh take"
        # History: [system, user] + [assistant response]
        assert len(player.turn_history) == 3

    @patch("src.nomic_engine.players.llm_player.PromptBuilder")
    @patch("src.nomic_engine.players.llm_player.create_api_client")
    @patch("src.nomic_engine.players.llm_player.parse_discussion_response")
    def test_discuss_without_begin_preserves_prior_rounds(
        self,
        mock_parse: MagicMock,
        mock_api_client_class: MagicMock,
        mock_prompt_builder_class: MagicMock,
        model_config: ModelDefinition,
        proposal: Proposal,
        game_state: GameState,
        rules: list[Rule],
    ) -> None:
        """Skipping begin_discussion_turn() retains accumulated history."""
        mock_api = mock_api_client_class.return_value
        mock_api.get_completion.return_value = CompletionResult(
            text='{"x":"y"}', raw_response=None, client_latency_ms=0
        )
        mock_parse.return_value = {
            "private_thoughts": "t",
            "discussion_text": "retained",
        }

        player = LLMPlayer("Bob", model_config)
        # Simulate history from previous withdrawal round
        accumulated = [
            ChatMessage(role="system", content="Round 1 system"),
            ChatMessage(role="assistant", content="Round 1 discussion"),
        ]
        player.turn_history = list(accumulated)

        # Do NOT call begin_discussion_turn() — history must be preserved
        result = player.discuss(proposal, game_state, rules)

        assert player.turn_history[0].content == "Round 1 system"
        assert player.turn_history[1].content == "Round 1 discussion"
        assert result.text == "retained"


# =====================================================================
# Sub-task B: GameLoop._collect_discussions() lifecycle management
# =====================================================================


class TestCollectDiscussionsLifecycle:
    """Tests for begin_discussion_turn() call/skip in _collect_discussions."""

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

    def test_first_attempt_calls_begin_discussion_turn(self) -> None:
        """is_retry=False calls begin_discussion_turn() before discuss()."""
        game_loop, _alice, bob = self._make_game_loop(retain_flag=True)
        proposal = self._make_proposal()

        game_loop._collect_discussions(
            proposal, game_loop.players, is_retry=False
        )

        bob.begin_discussion_turn.assert_called_once()
        bob.discuss.assert_called_once()

    def test_retry_with_flag_true_calls_on_proposal_updated(self) -> None:
        """is_retry=True + retain=True calls on_proposal_updated()."""
        game_loop, _alice, bob = self._make_game_loop(retain_flag=True)
        proposal = self._make_proposal()

        game_loop._collect_discussions(
            proposal,
            game_loop.players,
            is_retry=True,
            withdrawal_attempt=1,
            max_withdrawal_retries=2,
        )

        bob.begin_discussion_turn.assert_not_called()
        bob.on_proposal_updated.assert_called_once()
        bob.discuss.assert_called_once()

    def test_retry_with_flag_true_passes_attempt_numbers(self) -> None:
        """on_proposal_updated receives correct withdrawal attempt numbers."""
        game_loop, _alice, bob = self._make_game_loop(retain_flag=True)
        proposal = self._make_proposal()

        game_loop._collect_discussions(
            proposal,
            game_loop.players,
            is_retry=True,
            withdrawal_attempt=2,
            max_withdrawal_retries=3,
        )

        call_kwargs = bob.on_proposal_updated.call_args
        assert call_kwargs.kwargs["withdrawal_attempt"] == 2
        assert call_kwargs.kwargs["max_withdrawal_retries"] == 3

    def test_retry_with_flag_false_calls_begin_discussion_turn(self) -> None:
        """is_retry=True + retain=False calls begin_discussion_turn()."""
        game_loop, _alice, bob = self._make_game_loop(retain_flag=False)
        proposal = self._make_proposal()

        game_loop._collect_discussions(
            proposal, game_loop.players, is_retry=True
        )

        bob.begin_discussion_turn.assert_called_once()
        bob.discuss.assert_called_once()

    def test_proposer_skipped_for_all_discussion_methods(self) -> None:
        """Proposer must not have begin/on_proposal_updated/discuss called."""
        game_loop, alice, _bob = self._make_game_loop()
        proposal = self._make_proposal(proposer="Alice")

        game_loop._collect_discussions(
            proposal,
            game_loop.players,
            is_retry=True,
            withdrawal_attempt=1,
            max_withdrawal_retries=2,
        )

        alice.begin_discussion_turn.assert_not_called()
        alice.on_proposal_updated.assert_not_called()
        alice.discuss.assert_not_called()

    def test_no_game_config_calls_begin_discussion_turn(self) -> None:
        """game_config=None must behave like retain=False (no skip)."""
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

        # With no config, skip_init=False, so init IS called
        bob.begin_discussion_turn.assert_called_once()
        bob.discuss.assert_called_once()


# =====================================================================
# Sprint 30 Task 1: DISCUSS_PROPOSAL_UPDATED_TEMPLATE
# =====================================================================


class TestDiscussProposalUpdatedTemplate:
    """Tests for DISCUSS_PROPOSAL_UPDATED_TEMPLATE constant in prompts.py."""

    def test_template_exists(self) -> None:
        """DISCUSS_PROPOSAL_UPDATED_TEMPLATE must be defined in prompts."""
        assert hasattr(prompts, "DISCUSS_PROPOSAL_UPDATED_TEMPLATE")

    def test_template_has_required_placeholders(self) -> None:
        """Template must expose all required placeholder variables."""
        template = prompts.DISCUSS_PROPOSAL_UPDATED_TEMPLATE
        assert "{withdrawal_attempt}" in template
        assert "{max_withdrawal_retries}" in template
        assert "{proposal_block}" in template
        assert "{json_format_enforcement}" in template

    def test_template_formats_correctly(self) -> None:
        """Template must render without error when all placeholders filled."""
        rendered = prompts.DISCUSS_PROPOSAL_UPDATED_TEMPLATE.format(
            withdrawal_attempt=1,
            max_withdrawal_retries=2,
            proposal_block="=== PROPOSAL #301 ===\n...",
            json_format_enforcement=prompts.JSON_FORMAT_ENFORCEMENT,
        )
        assert "1" in rendered
        assert "2" in rendered
        assert "=== PROPOSAL #301 ===" in rendered


# =====================================================================
# Sprint 30 Task 1: LLMPlayer.on_proposal_updated
# =====================================================================


class TestLLMPlayerOnProposalUpdated:
    """Tests for LLMPlayer.on_proposal_updated()."""

    @patch("src.nomic_engine.players.llm_player.PromptBuilder")
    @patch("src.nomic_engine.players.llm_player.create_api_client")
    def test_appends_exactly_one_user_message(
        self,
        mock_api_client_class: MagicMock,
        mock_prompt_builder_class: MagicMock,
        model_config: ModelDefinition,
        proposal: Proposal,
        game_state: GameState,
        rules: list[Rule],
    ) -> None:
        """on_proposal_updated must append exactly one user message."""
        mock_pb = mock_prompt_builder_class.return_value
        mock_pb._format_proposal.return_value = "=== PROPOSAL #301 ===\n..."

        player = LLMPlayer("Bob", model_config)
        initial_history = [
            ChatMessage(role="system", content="Prior system"),
            ChatMessage(role="assistant", content="Prior discussion"),
        ]
        player.turn_history = list(initial_history)

        player.on_proposal_updated(
            proposal=proposal,
            game_state=game_state,
            rules=rules,
            withdrawal_attempt=1,
            max_withdrawal_retries=2,
        )

        # Exactly one message appended
        assert len(player.turn_history) == len(initial_history) + 1
        new_msg = player.turn_history[-1]
        assert new_msg.role == "user"

    @patch("src.nomic_engine.players.llm_player.PromptBuilder")
    @patch("src.nomic_engine.players.llm_player.create_api_client")
    def test_does_not_reset_history(
        self,
        mock_api_client_class: MagicMock,
        mock_prompt_builder_class: MagicMock,
        model_config: ModelDefinition,
        proposal: Proposal,
        game_state: GameState,
        rules: list[Rule],
    ) -> None:
        """on_proposal_updated must not reset turn_history."""
        mock_pb = mock_prompt_builder_class.return_value
        mock_pb._format_proposal.return_value = "=== PROPOSAL ==="

        player = LLMPlayer("Bob", model_config)
        player.turn_history = [
            ChatMessage(role="system", content="Keep this"),
            ChatMessage(role="assistant", content="Keep this too"),
        ]

        player.on_proposal_updated(
            proposal=proposal,
            game_state=game_state,
            rules=rules,
            withdrawal_attempt=1,
            max_withdrawal_retries=2,
        )

        # Original messages must be preserved
        assert player.turn_history[0].content == "Keep this"
        assert player.turn_history[1].content == "Keep this too"

    @patch("src.nomic_engine.players.llm_player.PromptBuilder")
    @patch("src.nomic_engine.players.llm_player.create_api_client")
    def test_message_contains_withdrawal_attempt_numbers(
        self,
        mock_api_client_class: MagicMock,
        mock_prompt_builder_class: MagicMock,
        model_config: ModelDefinition,
        proposal: Proposal,
        game_state: GameState,
        rules: list[Rule],
    ) -> None:
        """The appended message must contain withdrawal attempt numbers."""
        mock_pb = mock_prompt_builder_class.return_value
        mock_pb._format_proposal.return_value = "=== PROPOSAL ==="

        player = LLMPlayer("Bob", model_config)
        player.turn_history = [ChatMessage(role="system", content="sys")]

        player.on_proposal_updated(
            proposal=proposal,
            game_state=game_state,
            rules=rules,
            withdrawal_attempt=2,
            max_withdrawal_retries=3,
        )

        appended = player.turn_history[-1].content
        assert "2" in appended
        assert "3" in appended

    @patch("src.nomic_engine.players.llm_player.PromptBuilder")
    @patch("src.nomic_engine.players.llm_player.create_api_client")
    def test_message_contains_proposal_block(
        self,
        mock_api_client_class: MagicMock,
        mock_prompt_builder_class: MagicMock,
        model_config: ModelDefinition,
        proposal: Proposal,
        game_state: GameState,
        rules: list[Rule],
    ) -> None:
        """The appended message must contain the formatted proposal block."""
        mock_pb = mock_prompt_builder_class.return_value
        mock_pb._format_proposal.return_value = "=== PROPOSAL #301 ==="

        player = LLMPlayer("Bob", model_config)
        player.turn_history = [ChatMessage(role="system", content="sys")]

        player.on_proposal_updated(
            proposal=proposal,
            game_state=game_state,
            rules=rules,
            withdrawal_attempt=1,
            max_withdrawal_retries=2,
        )

        appended = player.turn_history[-1].content
        assert "=== PROPOSAL #301 ===" in appended


# =====================================================================
# Sprint 30 Task 1: HumanPlayer.on_proposal_updated
# =====================================================================


class TestHumanPlayerOnProposalUpdated:
    """Tests for HumanPlayer.on_proposal_updated()."""

    def test_prints_withdrawal_notice(
        self,
        proposal: Proposal,
        game_state: GameState,
        rules: list[Rule],
        capsys: pytest.CaptureFixture,
    ) -> None:
        """on_proposal_updated must print a withdrawal notice."""
        player = HumanPlayer("Bob")
        player.on_proposal_updated(
            proposal=proposal,
            game_state=game_state,
            rules=rules,
            withdrawal_attempt=1,
            max_withdrawal_retries=2,
        )
        captured = capsys.readouterr()
        # Must mention withdrawal
        assert "withdraw" in captured.out.lower()

    def test_prints_attempt_numbers(
        self,
        proposal: Proposal,
        game_state: GameState,
        rules: list[Rule],
        capsys: pytest.CaptureFixture,
    ) -> None:
        """on_proposal_updated must print withdrawal attempt numbers."""
        player = HumanPlayer("Bob")
        player.on_proposal_updated(
            proposal=proposal,
            game_state=game_state,
            rules=rules,
            withdrawal_attempt=2,
            max_withdrawal_retries=3,
        )
        captured = capsys.readouterr()
        assert "2" in captured.out
        assert "3" in captured.out

    def test_prints_new_proposal_details(
        self,
        game_state: GameState,
        rules: list[Rule],
        capsys: pytest.CaptureFixture,
    ) -> None:
        """on_proposal_updated must print the new proposal's type and text."""
        player = HumanPlayer("Bob")
        new_proposal = Proposal(
            proposer_name="Alice",
            move_number=1,
            type=ProposalType.ADD,
            proposal_id="302",
            new_text="A brand new rule",
            rationale="Fresh start",
        )
        player.on_proposal_updated(
            proposal=new_proposal,
            game_state=game_state,
            rules=rules,
            withdrawal_attempt=1,
            max_withdrawal_retries=2,
        )
        captured = capsys.readouterr()
        # ProposalType.ADD.value is "Add"
        assert "Add" in captured.out
        assert "A brand new rule" in captured.out
        assert "Fresh start" in captured.out

    def test_does_not_prompt_for_input(
        self,
        proposal: Proposal,
        game_state: GameState,
        rules: list[Rule],
    ) -> None:
        """on_proposal_updated must not call input() — purely informational."""
        player = HumanPlayer("Bob")
        # If input() is called without patching it will block; we use
        # a patch that raises an error if called.
        err = AssertionError("input() called")
        with patch("builtins.input", side_effect=err):
            player.on_proposal_updated(
                proposal=proposal,
                game_state=game_state,
                rules=rules,
                withdrawal_attempt=1,
                max_withdrawal_retries=2,
            )


# =====================================================================
# Sprint 38 Task 4: WITHDRAWAL_LAST_ATTEMPT_TEMPLATE
# =====================================================================


class TestWithdrawalLastAttemptTemplate:
    """Tests for WITHDRAWAL_LAST_ATTEMPT_TEMPLATE constant in prompts.py."""

    def test_template_exists(self) -> None:
        """WITHDRAWAL_LAST_ATTEMPT_TEMPLATE must be defined in prompts."""
        assert hasattr(prompts, "WITHDRAWAL_LAST_ATTEMPT_TEMPLATE")

    def test_template_has_required_placeholders(self) -> None:
        """Template must contain both attempt-count placeholders."""
        template = prompts.WITHDRAWAL_LAST_ATTEMPT_TEMPLATE
        assert "{withdrawal_attempt}" in template
        assert "{max_withdrawal_retries}" in template

    def test_template_formats_without_error(self) -> None:
        """Template must render without error when all placeholders filled."""
        rendered = prompts.WITHDRAWAL_LAST_ATTEMPT_TEMPLATE.format(
            withdrawal_attempt=3,
            max_withdrawal_retries=3,
        )
        assert "3" in rendered

    def test_template_signals_turn_end_consequence(self) -> None:
        """Template must mention that withdrawal will skip or end the turn."""
        rendered = prompts.WITHDRAWAL_LAST_ATTEMPT_TEMPLATE.format(
            withdrawal_attempt=3,
            max_withdrawal_retries=3,
        )
        lower = rendered.lower()
        assert any(
            word in lower for word in ("skip", "end", "no vote", "skipped")
        )


# =====================================================================
# Sprint 38 Task 4: LLMPlayer.note_withdrawal_for_retry template selection
# =====================================================================


class TestLLMPlayerNoteWithdrawalLastAttempt:
    """Tests for LLMPlayer.note_withdrawal_for_retry() template selection."""

    @patch("src.nomic_engine.players.llm_player.PromptBuilder")
    @patch("src.nomic_engine.players.llm_player.create_api_client")
    def test_last_attempt_uses_last_attempt_template(
        self,
        mock_api_client_class: MagicMock,
        mock_prompt_builder_class: MagicMock,
        model_config: ModelDefinition,
    ) -> None:
        """On the final attempt, note_withdrawal_for_retry must use
        WITHDRAWAL_LAST_ATTEMPT_TEMPLATE."""
        player = LLMPlayer("Alice", model_config)
        player.turn_history = [ChatMessage(role="system", content="sys")]

        player.note_withdrawal_for_retry(
            discussions=[],
            withdrawal_attempt=2,
            max_withdrawal_retries=2,
        )

        appended = player.turn_history[-1].content
        # Should contain last-attempt signal keywords
        lower = appended.lower()
        assert any(
            word in lower
            for word in ("last", "skip", "end", "no vote", "skipped")
        )
        # Should NOT contain intermediate-attempt language
        assert "another proposal opportunity" not in appended

    @patch("src.nomic_engine.players.llm_player.PromptBuilder")
    @patch("src.nomic_engine.players.llm_player.create_api_client")
    def test_intermediate_attempt_uses_retry_template(
        self,
        mock_api_client_class: MagicMock,
        mock_prompt_builder_class: MagicMock,
        model_config: ModelDefinition,
    ) -> None:
        """On non-final attempts, note_withdrawal_for_retry must use
        WITHDRAWAL_RETRY_TEMPLATE."""
        player = LLMPlayer("Alice", model_config)
        player.turn_history = [ChatMessage(role="system", content="sys")]

        player.note_withdrawal_for_retry(
            discussions=[],
            withdrawal_attempt=1,
            max_withdrawal_retries=2,
        )

        appended = player.turn_history[-1].content
        # Should match WITHDRAWAL_RETRY_TEMPLATE (no last-attempt language)
        lower = appended.lower()
        assert "last" not in lower or "last attempt" not in lower
        # The WITHDRAWAL_RETRY_TEMPLATE text should be there
        assert "withdrawn" in lower


# =====================================================================
# Sprint 38 Task 4: HumanPlayer.propose() last-attempt output
# =====================================================================


class TestHumanPlayerProposeLastAttempt:
    """Tests for HumanPlayer.propose() last-attempt withdrawal guidance."""

    def test_last_attempt_prints_turn_end_signal(
        self,
        game_state: GameState,
        rules: list[Rule],
        capsys: pytest.CaptureFixture,
    ) -> None:
        """On the last attempt, propose() must print about turn ending."""
        player = HumanPlayer("Alice")
        with patch("builtins.input") as mock_input:
            mock_input.side_effect = ["A", "New rule text", "rationale"]
            player.propose(
                game_state,
                rules,
                continue_turn=True,
                withdrawal_attempt=3,
                max_withdrawal_retries=3,
            )

        captured = capsys.readouterr()
        lower = captured.out.lower()
        assert any(
            word in lower for word in ("skip", "end", "no vote", "skipped")
        )

    def test_last_attempt_does_not_say_another_opportunity(
        self,
        game_state: GameState,
        rules: list[Rule],
        capsys: pytest.CaptureFixture,
    ) -> None:
        """On the last attempt, propose() must not claim another
        opportunity remains."""
        player = HumanPlayer("Alice")
        with patch("builtins.input") as mock_input:
            mock_input.side_effect = ["A", "New rule text", "rationale"]
            player.propose(
                game_state,
                rules,
                continue_turn=True,
                withdrawal_attempt=3,
                max_withdrawal_retries=3,
            )

        captured = capsys.readouterr()
        assert "another proposal opportunity" not in captured.out

    def test_intermediate_attempt_says_another_opportunity(
        self,
        game_state: GameState,
        rules: list[Rule],
        capsys: pytest.CaptureFixture,
    ) -> None:
        """On an intermediate attempt, propose() keeps original guidance."""
        player = HumanPlayer("Alice")
        with patch("builtins.input") as mock_input:
            mock_input.side_effect = ["A", "New rule text", "rationale"]
            player.propose(
                game_state,
                rules,
                continue_turn=True,
                withdrawal_attempt=1,
                max_withdrawal_retries=3,
            )

        captured = capsys.readouterr()
        assert "another proposal opportunity" in captured.out
