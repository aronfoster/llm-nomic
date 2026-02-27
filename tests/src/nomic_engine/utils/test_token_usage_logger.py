"""
Unit tests for TokenUsageLogger and related token usage infrastructure.

Coverage:
- TokenUsageLogger write behaviour (happy path, file append, JSON Lines format)
- TokenUsageLogger null/error handling (write failures → WARNING, never raise)
- build_token_usage_record: metadata extraction per provider
- build_token_usage_record: null handling when raw_response is None
- TokenUsageRecord field validation
- call_type correctness ensured by the caller (tested via LLMPlayer/LLMJudge)
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from src.nomic_engine.data_models import (
    CompletionResult,
    ModelDefinition,
    TokenUsageRecord,
)
from src.nomic_engine.llm.api_clients import build_token_usage_record
from src.nomic_engine.utils.token_usage_logger import TokenUsageLogger

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_model(
    provider: str, api_model_id: str = "test-model"
) -> ModelDefinition:
    return ModelDefinition(
        id="test",
        provider=provider,
        api_model_id=api_model_id,
        env_key_name=None,
    )


def _make_result(
    text: str | None = "hello",
    raw_response: object = None,
    client_latency_ms: int = 42,
) -> CompletionResult:
    return CompletionResult(
        text=text,
        raw_response=raw_response,
        client_latency_ms=client_latency_ms,
    )


def _minimal_record(**overrides: object) -> TokenUsageRecord:
    defaults: dict[str, object] = dict(
        timestamp="2026-02-25T14:32:01.000Z",
        move_number=1,
        player_name="Alice",
        provider="anthropic",
        model_id="claude-sonnet-4-5",
        call_type="propose",
        input_tokens=100,
        output_tokens=50,
        cache_creation_tokens=None,
        cache_read_tokens=None,
        reasoning_tokens=None,
        finish_reason=None,
        client_latency_ms=42,
        server_latency_ms=None,
        ttft_ms=None,
        mean_itl_ms=None,
        request_id=None,
        ratelimit_remaining_requests=None,
        ratelimit_remaining_tokens=None,
    )
    defaults.update(overrides)
    return TokenUsageRecord(**defaults)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# TokenUsageRecord field validation
# ---------------------------------------------------------------------------


class TestTokenUsageRecord:
    def test_required_fields_present(self) -> None:
        """All required fields must be set without defaults."""
        record = _minimal_record()
        assert record.move_number == 1
        assert record.player_name == "Alice"
        assert record.provider == "anthropic"

    def test_nullable_fields_accept_none(self) -> None:
        """Nullable fields accept None without validation error."""
        record = _minimal_record(
            cache_creation_tokens=None,
            cache_read_tokens=None,
            reasoning_tokens=None,
            finish_reason=None,
            server_latency_ms=None,
            ttft_ms=None,
            mean_itl_ms=None,
            request_id=None,
            ratelimit_remaining_requests=None,
            ratelimit_remaining_tokens=None,
        )
        assert record.cache_creation_tokens is None
        assert record.ratelimit_remaining_tokens is None

    def test_nullable_fields_accept_values(self) -> None:
        """Nullable fields accept non-None values."""
        record = _minimal_record(
            cache_creation_tokens=3600,
            cache_read_tokens=0,
            reasoning_tokens=200,
            finish_reason="end_turn",
            server_latency_ms=1890.4,
            ttft_ms=436.4,
            mean_itl_ms=11.1,
            request_id="req-123",
            ratelimit_remaining_requests=607,
            ratelimit_remaining_tokens=4000000,
        )
        assert record.cache_creation_tokens == 3600
        assert record.finish_reason == "end_turn"
        assert record.ratelimit_remaining_tokens == 4000000

    def test_model_dump_json_round_trips(self) -> None:
        """model_dump_json produces valid JSON with all expected keys."""
        record = _minimal_record(
            cache_creation_tokens=100,
            finish_reason="stop",
        )
        json_str = record.model_dump_json()
        parsed = json.loads(json_str)
        assert parsed["move_number"] == 1
        assert parsed["player_name"] == "Alice"
        assert parsed["cache_creation_tokens"] == 100
        assert parsed["finish_reason"] == "stop"
        assert parsed["reasoning_tokens"] is None

    def test_timestamp_format(self) -> None:
        """Timestamp field accepts ISO 8601 UTC strings ending with Z."""
        record = _minimal_record(timestamp="2026-02-25T14:32:01.123Z")
        assert record.timestamp == "2026-02-25T14:32:01.123Z"


# ---------------------------------------------------------------------------
# TokenUsageLogger – write behaviour
# ---------------------------------------------------------------------------


class TestTokenUsageLogger:
    def test_log_writes_json_line(self, tmp_path: Path) -> None:
        """log() appends a valid JSON line to the file."""
        log_file = tmp_path / "token_usage.jsonl"
        log_file.touch()
        logger = TokenUsageLogger(log_file)
        record = _minimal_record()

        logger.log(record)

        lines = log_file.read_text().strip().splitlines()
        assert len(lines) == 1
        parsed = json.loads(lines[0])
        assert parsed["player_name"] == "Alice"
        assert parsed["move_number"] == 1

    def test_log_appends_multiple_records(self, tmp_path: Path) -> None:
        """Calling log() multiple times appends separate JSON lines."""
        log_file = tmp_path / "token_usage.jsonl"
        log_file.touch()
        logger = TokenUsageLogger(log_file)

        logger.log(_minimal_record(move_number=1))
        logger.log(_minimal_record(move_number=2))
        logger.log(_minimal_record(move_number=3))

        lines = log_file.read_text().strip().splitlines()
        assert len(lines) == 3
        assert json.loads(lines[0])["move_number"] == 1
        assert json.loads(lines[2])["move_number"] == 3

    def test_log_never_raises_on_write_failure(self, tmp_path: Path) -> None:
        """Failed writes log a WARNING and never raise."""
        log_file = tmp_path / "token_usage.jsonl"
        logger = TokenUsageLogger(log_file)
        record = _minimal_record()

        # Point the path at a directory (unwritable as a file)
        log_file.mkdir()

        # Should not raise; should log a warning
        with patch(
            "src.nomic_engine.utils.token_usage_logger.logger"
        ) as mock_logger:
            logger.log(record)
            mock_logger.warning.assert_called_once()

    def test_log_uses_model_dump_json(self, tmp_path: Path) -> None:
        """log() serialises via model_dump_json so all field names match."""
        log_file = tmp_path / "token_usage.jsonl"
        log_file.touch()
        logger = TokenUsageLogger(log_file)
        record = _minimal_record(call_type="judge_veto")

        logger.log(record)

        parsed = json.loads(log_file.read_text().strip())
        # Verify snake_case field names from the model
        assert "call_type" in parsed
        assert parsed["call_type"] == "judge_veto"
        assert "client_latency_ms" in parsed


# ---------------------------------------------------------------------------
# build_token_usage_record – null handling (raw_response is None / on error)
# ---------------------------------------------------------------------------


class TestBuildTokenUsageRecordNullHandling:
    def test_null_raw_response_yields_zero_tokens(self) -> None:
        """When raw_response is None all token fields default to 0 or null."""
        result = _make_result(text=None, raw_response=None)
        record = build_token_usage_record(
            result=result,
            model_config=_make_model("anthropic"),
            call_type="propose",
            move_number=3,
            player_name="Alice",
        )
        assert record.input_tokens == 0
        assert record.output_tokens == 0
        assert record.cache_creation_tokens is None
        assert record.cache_read_tokens is None
        assert record.reasoning_tokens is None
        assert record.finish_reason is None
        assert record.request_id is None
        assert record.ratelimit_remaining_requests is None
        assert record.ratelimit_remaining_tokens is None

    def test_client_latency_always_preserved(self) -> None:
        """client_latency_ms is copied from CompletionResult even on error."""
        result = _make_result(
            text=None, raw_response=None, client_latency_ms=999
        )
        record = build_token_usage_record(
            result=result,
            model_config=_make_model("openai"),
            call_type="vote",
            move_number=1,
            player_name="Bob",
        )
        assert record.client_latency_ms == 999

    def test_unknown_provider_yields_null_meta(self) -> None:
        """Unknown provider yields 0 tokens and null for optional fields."""
        result = _make_result(raw_response=MagicMock())
        record = build_token_usage_record(
            result=result,
            model_config=_make_model("unknown_provider"),
            call_type="discuss",
            move_number=1,
            player_name="Alice",
        )
        assert record.input_tokens == 0
        assert record.finish_reason is None

    def test_context_fields_set_correctly(self) -> None:
        """move_number, player_name, call_type, provider, model_id are set."""
        result = _make_result(raw_response=None)
        record = build_token_usage_record(
            result=result,
            model_config=_make_model("anthropic", "claude-sonnet-4-5"),
            call_type="revise",
            move_number=7,
            player_name="Charlie",
        )
        assert record.move_number == 7
        assert record.player_name == "Charlie"
        assert record.call_type == "revise"
        assert record.provider == "anthropic"
        assert record.model_id == "claude-sonnet-4-5"

    def test_timestamp_is_utc_and_ends_with_z(self) -> None:
        """Generated timestamp ends with 'Z' (UTC indicator)."""
        result = _make_result(raw_response=None)
        record = build_token_usage_record(
            result=result,
            model_config=_make_model("google"),
            call_type="judge_score",
            move_number=1,
            player_name="Judge",
        )
        assert record.timestamp.endswith("Z")
        # Should be ISO 8601-ish: YYYY-MM-DDTHH:MM:SS.mmmZ
        assert "T" in record.timestamp


# ---------------------------------------------------------------------------
# build_token_usage_record – Anthropic provider extraction
# ---------------------------------------------------------------------------


class TestBuildTokenUsageRecordAnthropic:
    def _make_anthropic_response(
        self,
        input_tokens: int = 100,
        output_tokens: int = 50,
        cache_creation: int | None = None,
        cache_read: int | None = None,
        stop_reason: str | None = "end_turn",
    ) -> MagicMock:
        mock = MagicMock()
        mock.usage.input_tokens = input_tokens
        mock.usage.output_tokens = output_tokens
        mock.usage.cache_creation_input_tokens = cache_creation
        mock.usage.cache_read_input_tokens = cache_read
        mock.stop_reason = stop_reason
        return mock

    def test_extracts_input_and_output_tokens(self) -> None:
        raw = self._make_anthropic_response(
            input_tokens=3821, output_tokens=214
        )
        result = _make_result(raw_response=raw)
        record = build_token_usage_record(
            result=result,
            model_config=_make_model("anthropic"),
            call_type="propose",
            move_number=4,
            player_name="Alice",
        )
        assert record.input_tokens == 3821
        assert record.output_tokens == 214

    def test_extracts_cache_tokens(self) -> None:
        raw = self._make_anthropic_response(cache_creation=3600, cache_read=0)
        result = _make_result(raw_response=raw)
        record = build_token_usage_record(
            result=result,
            model_config=_make_model("anthropic"),
            call_type="discuss",
            move_number=1,
            player_name="Alice",
        )
        assert record.cache_creation_tokens == 3600
        assert record.cache_read_tokens == 0

    def test_cache_tokens_null_when_absent(self) -> None:
        raw = self._make_anthropic_response(
            cache_creation=None, cache_read=None
        )
        result = _make_result(raw_response=raw)
        record = build_token_usage_record(
            result=result,
            model_config=_make_model("anthropic"),
            call_type="vote",
            move_number=1,
            player_name="Bob",
        )
        assert record.cache_creation_tokens is None
        assert record.cache_read_tokens is None

    def test_extracts_finish_reason(self) -> None:
        raw = self._make_anthropic_response(stop_reason="max_tokens")
        result = _make_result(raw_response=raw)
        record = build_token_usage_record(
            result=result,
            model_config=_make_model("anthropic"),
            call_type="propose",
            move_number=1,
            player_name="Alice",
        )
        assert record.finish_reason == "max_tokens"

    def test_reasoning_tokens_always_null_for_anthropic(self) -> None:
        raw = self._make_anthropic_response()
        result = _make_result(raw_response=raw)
        record = build_token_usage_record(
            result=result,
            model_config=_make_model("anthropic"),
            call_type="propose",
            move_number=1,
            player_name="Alice",
        )
        assert record.reasoning_tokens is None

    def test_headers_null_for_standard_response(self) -> None:
        """Standard parsed response: request_id etc. are null."""
        raw = self._make_anthropic_response()
        result = _make_result(raw_response=raw)
        record = build_token_usage_record(
            result=result,
            model_config=_make_model("anthropic"),
            call_type="propose",
            move_number=1,
            player_name="Alice",
        )
        assert record.request_id is None
        assert record.ratelimit_remaining_requests is None
        assert record.ratelimit_remaining_tokens is None

    def test_extraction_survives_missing_usage_attribute(self) -> None:
        """If usage is missing entirely, tokens default to 0."""
        raw = MagicMock()
        del raw.usage  # remove usage attribute
        raw.stop_reason = "end_turn"
        result = _make_result(raw_response=raw)
        record = build_token_usage_record(
            result=result,
            model_config=_make_model("anthropic"),
            call_type="propose",
            move_number=1,
            player_name="Alice",
        )
        assert record.input_tokens == 0
        assert record.output_tokens == 0


# ---------------------------------------------------------------------------
# build_token_usage_record – OpenAI provider extraction
# ---------------------------------------------------------------------------


class TestBuildTokenUsageRecordOpenAI:
    def _make_openai_response(
        self,
        prompt_tokens: int = 200,
        completion_tokens: int = 80,
        reasoning_tokens: int | None = None,
        finish_reason: str | None = "stop",
    ) -> MagicMock:
        mock = MagicMock()
        mock.usage.prompt_tokens = prompt_tokens
        mock.usage.completion_tokens = completion_tokens
        details = MagicMock()
        details.reasoning_tokens = reasoning_tokens
        mock.usage.completion_tokens_details = details
        choice = MagicMock()
        choice.finish_reason = finish_reason
        mock.choices = [choice]
        return mock

    def test_extracts_prompt_and_completion_tokens(self) -> None:
        raw = self._make_openai_response(
            prompt_tokens=500, completion_tokens=100
        )
        result = _make_result(raw_response=raw)
        record = build_token_usage_record(
            result=result,
            model_config=_make_model("openai"),
            call_type="vote",
            move_number=2,
            player_name="Alice",
        )
        assert record.input_tokens == 500
        assert record.output_tokens == 100

    def test_extracts_reasoning_tokens_for_openai(self) -> None:
        raw = self._make_openai_response(reasoning_tokens=150)
        result = _make_result(raw_response=raw)
        record = build_token_usage_record(
            result=result,
            model_config=_make_model("openai"),
            call_type="propose",
            move_number=1,
            player_name="Alice",
        )
        assert record.reasoning_tokens == 150

    def test_reasoning_tokens_reported_for_xai(self) -> None:
        """reasoning_tokens should be logged as-reported for xai provider."""
        raw = self._make_openai_response(reasoning_tokens=100)
        result = _make_result(raw_response=raw)
        record = build_token_usage_record(
            result=result,
            model_config=_make_model("xai"),
            call_type="propose",
            move_number=1,
            player_name="Alice",
        )
        assert record.reasoning_tokens == 100

    def test_reasoning_tokens_null_for_local(self) -> None:
        """reasoning_tokens should be null for local provider."""
        raw = self._make_openai_response(reasoning_tokens=50)
        result = _make_result(raw_response=raw)
        record = build_token_usage_record(
            result=result,
            model_config=_make_model("local"),
            call_type="discuss",
            move_number=1,
            player_name="Alice",
        )
        assert record.reasoning_tokens is None

    def test_extracts_finish_reason(self) -> None:
        raw = self._make_openai_response(finish_reason="length")
        result = _make_result(raw_response=raw)
        record = build_token_usage_record(
            result=result,
            model_config=_make_model("openai"),
            call_type="discuss",
            move_number=1,
            player_name="Alice",
        )
        assert record.finish_reason == "length"

    def test_null_when_raw_response_is_none(self) -> None:
        result = _make_result(raw_response=None)
        record = build_token_usage_record(
            result=result,
            model_config=_make_model("openai"),
            call_type="vote",
            move_number=1,
            player_name="Alice",
        )
        assert record.input_tokens == 0
        assert record.output_tokens == 0
        assert record.finish_reason is None


# ---------------------------------------------------------------------------
# build_token_usage_record – Google provider extraction
# ---------------------------------------------------------------------------


class TestBuildTokenUsageRecordGoogle:
    def _make_google_response(
        self,
        prompt_tokens: int = 300,
        candidate_tokens: int = 60,
        finish_reason: str | None = "STOP",
    ) -> MagicMock:
        mock = MagicMock()
        mock.usage_metadata.prompt_token_count = prompt_tokens
        mock.usage_metadata.candidates_token_count = candidate_tokens
        candidate = MagicMock()
        candidate.finish_reason = finish_reason
        mock.candidates = [candidate]
        return mock

    def test_extracts_token_counts(self) -> None:
        raw = self._make_google_response(
            prompt_tokens=300, candidate_tokens=60
        )
        result = _make_result(raw_response=raw)
        record = build_token_usage_record(
            result=result,
            model_config=_make_model("google"),
            call_type="judge_veto",
            move_number=5,
            player_name="Judge",
        )
        assert record.input_tokens == 300
        assert record.output_tokens == 60

    def test_extracts_finish_reason(self) -> None:
        raw = self._make_google_response(finish_reason="STOP")
        result = _make_result(raw_response=raw)
        record = build_token_usage_record(
            result=result,
            model_config=_make_model("google"),
            call_type="judge_score",
            move_number=1,
            player_name="Judge",
        )
        assert record.finish_reason == "STOP"

    def test_cache_and_reasoning_always_null(self) -> None:
        raw = self._make_google_response()
        result = _make_result(raw_response=raw)
        record = build_token_usage_record(
            result=result,
            model_config=_make_model("google"),
            call_type="discuss",
            move_number=1,
            player_name="Alice",
        )
        assert record.cache_creation_tokens is None
        assert record.cache_read_tokens is None
        assert record.reasoning_tokens is None
        assert record.server_latency_ms is None
        assert record.ttft_ms is None
        assert record.mean_itl_ms is None

    def test_null_raw_response(self) -> None:
        result = _make_result(raw_response=None)
        record = build_token_usage_record(
            result=result,
            model_config=_make_model("google"),
            call_type="memory_update",
            move_number=2,
            player_name="Alice",
        )
        assert record.input_tokens == 0
        assert record.finish_reason is None


# ---------------------------------------------------------------------------
# call_type correctness tests (verifying each call site uses the right value)
# ---------------------------------------------------------------------------


class TestCallTypesViaLLMPlayer:
    """Verify that each LLMPlayer call site logs the correct call_type."""

    def _make_player_with_logger(
        self, tmp_path: Path
    ) -> tuple[object, TokenUsageLogger, Path]:
        from src.nomic_engine.players.llm_player import LLMPlayer

        log_file = tmp_path / "token_usage.jsonl"
        log_file.touch()
        usage_logger = TokenUsageLogger(log_file)

        model_config = _make_model("local", "http://localhost:11434/v1")
        with patch("src.nomic_engine.llm.api_clients.OpenAI"):
            player = LLMPlayer(
                "Alice",
                model_config,
                token_usage_logger=usage_logger,
            )
        return player, usage_logger, log_file

    def _make_game_state(self, move_number: int = 1) -> object:
        from src.nomic_engine.data_models import GameState

        return GameState(
            scores={"Alice": 0},
            current_player_name="Alice",
            move_number=move_number,
            turn_order=["Alice"],
            next_proposal_id=301,
        )

    def _make_rules(self) -> list:
        from src.nomic_engine.data_models import Rule, RuleStatus

        return [
            Rule(rule_id="101", text="Base rule.", status=RuleStatus.IMMUTABLE)
        ]

    def _make_proposal(self) -> object:
        from src.nomic_engine.data_models import Proposal, ProposalType

        return Proposal(
            proposer_name="Alice",
            move_number=1,
            type=ProposalType.ADD,
            proposal_id="301",
            new_text="New rule",
            rationale="reason",
        )

    def _cr(self, text: str | None) -> CompletionResult:
        return CompletionResult(
            text=text, raw_response=None, client_latency_ms=10
        )

    def test_propose_call_type(self, tmp_path: Path) -> None:
        """propose() logs call_type='propose'."""
        player, _, log_file = self._make_player_with_logger(tmp_path)
        game_state = self._make_game_state()
        rules = self._make_rules()

        valid_json = (
            '{"type":"Add","target_rule_id":null,"new_text":"text",'
            '"rationale":"r","private_thoughts":"strategic"}'
        )
        player.api_client.get_completion = MagicMock(  # type: ignore[union-attr]
            return_value=self._cr(valid_json)
        )

        player.propose(game_state, rules)  # type: ignore[union-attr]

        lines = log_file.read_text().strip().splitlines()
        assert len(lines) >= 1
        record = json.loads(lines[0])
        assert record["call_type"] == "propose"
        assert record["move_number"] == 1

    def test_discuss_call_type(self, tmp_path: Path) -> None:
        """discuss() logs call_type='discuss'."""
        player, _, log_file = self._make_player_with_logger(tmp_path)
        game_state = self._make_game_state(move_number=2)
        rules = self._make_rules()
        proposal = self._make_proposal()

        valid_json = '{"discussion_text":"I agree","private_thoughts":"ok"}'
        player.api_client.get_completion = MagicMock(  # type: ignore[union-attr]
            return_value=self._cr(valid_json)
        )

        player.begin_discussion_turn(proposal, game_state, rules)  # type: ignore[union-attr]
        player.discuss(proposal, game_state, rules)  # type: ignore[union-attr]

        lines = log_file.read_text().strip().splitlines()
        assert any(
            json.loads(line)["call_type"] == "discuss" for line in lines
        )

    def test_vote_call_type(self, tmp_path: Path) -> None:
        """vote() logs call_type='vote'."""
        player, _, log_file = self._make_player_with_logger(tmp_path)
        game_state = self._make_game_state()
        rules = self._make_rules()
        proposal = self._make_proposal()

        valid_json = (
            '{"vote":"YES","public_reason":"good",'
            '"private_thoughts":"analysis"}'
        )
        player.api_client.get_completion = MagicMock(  # type: ignore[union-attr]
            return_value=self._cr(valid_json)
        )
        # Need turn history initialised for vote
        player.begin_discussion_turn(proposal, game_state, rules)  # type: ignore[union-attr]
        player.api_client.get_completion.reset_mock()  # type: ignore[union-attr]
        player.api_client.get_completion.return_value = self._cr(valid_json)  # type: ignore[union-attr]

        player.vote(proposal, game_state, rules)  # type: ignore[union-attr]

        lines = log_file.read_text().strip().splitlines()
        vote_lines = [
            json.loads(line)
            for line in lines
            if json.loads(line)["call_type"] == "vote"
        ]
        assert len(vote_lines) == 1

    def test_memory_update_call_type(self, tmp_path: Path) -> None:
        """update_memory() logs call_type='memory_update'."""
        from unittest.mock import MagicMock as MM

        from src.nomic_engine.memory.memory_manager import MemoryManager

        player, _, log_file = self._make_player_with_logger(tmp_path)
        # Attach a real-ish memory manager
        mock_mm = MM(spec=MemoryManager)
        mock_mm.max_characters = 0
        mock_mm.read.return_value = ""
        mock_mm.write = MM()
        player.memory_manager = mock_mm  # type: ignore[union-attr]

        long_response = "M" * 100
        player.api_client.get_completion = MM(  # type: ignore[union-attr]
            return_value=self._cr(long_response)
        )

        player.update_memory()  # type: ignore[union-attr]

        lines = log_file.read_text().strip().splitlines()
        types = [json.loads(line)["call_type"] for line in lines]
        assert "memory_update" in types


class TestCallTypesViaLLMJudge:
    """Verify that each LLMJudge call site logs the correct call_type."""

    def _make_judge_with_logger(
        self, tmp_path: Path
    ) -> tuple[object, TokenUsageLogger, Path]:
        from src.nomic_engine.judge.llm_judge import LLMJudge

        log_file = tmp_path / "token_usage.jsonl"
        log_file.touch()
        usage_logger = TokenUsageLogger(log_file)

        model_config = _make_model("local", "http://localhost:11434/v1")
        api_client_mock = MagicMock()
        judge = LLMJudge(
            model_config,
            api_client=api_client_mock,
            token_usage_logger=usage_logger,
        )
        return judge, usage_logger, log_file

    def _make_game_manager(self, move_number: int = 5) -> MagicMock:
        from src.nomic_engine.data_models import GameState, Rule, RuleStatus

        game_state = GameState(
            scores={"Alice": 0},
            current_player_name="Alice",
            move_number=move_number,
            turn_order=["Alice"],
            next_proposal_id=301,
        )
        rules_manager = MagicMock()
        rules_manager.rules = [
            Rule(
                rule_id="101",
                text="Base rule.",
                status=RuleStatus.IMMUTABLE,
            )
        ]
        mgr = MagicMock()
        mgr.game_state = game_state
        mgr.rules_manager = rules_manager
        return mgr

    def _cr(self, text: str | None) -> CompletionResult:
        return CompletionResult(
            text=text, raw_response=None, client_latency_ms=5
        )

    def test_judge_veto_call_type(self, tmp_path: Path) -> None:
        """get_veto() logs call_type='judge_veto'."""
        judge, _, log_file = self._make_judge_with_logger(tmp_path)
        mgr = self._make_game_manager()

        prompt_builder = MagicMock()
        prompt_builder.build_judge_context_block.return_value = ""
        prompt_builder.build_judge_veto_prompt.return_value = MagicMock()
        judge.prompt_builder = prompt_builder  # type: ignore[union-attr]

        veto_json = '{"veto":false,"reason":"ok","private_thoughts":"x"}'
        judge.api_client.get_completion.return_value = self._cr(veto_json)  # type: ignore[union-attr]

        judge.get_veto(mgr, MagicMock(), [], [])  # type: ignore[union-attr]

        lines = log_file.read_text().strip().splitlines()
        types = [json.loads(line)["call_type"] for line in lines]
        assert "judge_veto" in types

    def test_judge_score_call_type(self, tmp_path: Path) -> None:
        """assess_scores() logs call_type='judge_score'."""
        judge, _, log_file = self._make_judge_with_logger(tmp_path)
        mgr = self._make_game_manager()

        prompt_builder = MagicMock()
        prompt_builder.build_judge_score_prompt.return_value = MagicMock()
        judge.prompt_builder = prompt_builder  # type: ignore[union-attr]

        score_json = '{"private_thoughts":"ok","score_adjustments":[]}'
        judge.api_client.get_completion.return_value = self._cr(score_json)  # type: ignore[union-attr]

        judge.assess_scores(mgr, [], MagicMock(), [], [], proposal_passed=True)  # type: ignore[union-attr]

        lines = log_file.read_text().strip().splitlines()
        types = [json.loads(line)["call_type"] for line in lines]
        assert "judge_score" in types

    def test_judge_maintain_state_call_type(self, tmp_path: Path) -> None:
        """maintain_state() logs call_type='judge_maintain_state'."""
        judge, _, log_file = self._make_judge_with_logger(tmp_path)
        mgr = self._make_game_manager()

        prompt_builder = MagicMock()
        prompt_builder.build_judge_maintain_state_prompt.return_value = (
            MagicMock()
        )
        judge.prompt_builder = prompt_builder  # type: ignore[union-attr]

        state_json = (
            '{"private_thoughts":"none","flags":{},"target_score":null}'
        )
        judge.api_client.get_completion.return_value = self._cr(state_json)  # type: ignore[union-attr]

        judge.maintain_state(mgr, MagicMock(), None, None)  # type: ignore[union-attr]

        lines = log_file.read_text().strip().splitlines()
        types = [json.loads(line)["call_type"] for line in lines]
        assert "judge_maintain_state" in types
