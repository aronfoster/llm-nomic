"""
Abstract base class for all player types in the Nomic game.

This module defines the interface that all player implementations
(human, LLM, etc.) must follow.
"""

from abc import ABC, abstractmethod

from ..data_models import Discussion, GameState, Proposal, Rule, Vote


class BasePlayer(ABC):
    """
    Abstract base class defining the player interface.

    All player implementations must inherit from this class and
    implement the three core methods: propose, discuss, and vote.
    """

    def __init__(self, player_name: str) -> None:
        """
        Initialize a player with a name.

        Args:
            player_name: The unique name of this player.
        """
        self.player_name = player_name

    @abstractmethod
    def propose(
        self,
        game_state: GameState,
        rules: list[Rule],
        continue_turn: bool = False,
        withdrawal_attempt: int = 0,
        max_withdrawal_retries: int = 0,
    ) -> Proposal:
        """
        Generate a proposal for a rule change.

        Args:
            game_state: The current state of the game.
            rules: The current list of all rules.
            continue_turn: True when retrying after a withdrawal so the
                player can preserve cumulative context.
            withdrawal_attempt: The current withdrawal attempt number
                (0 on the first attempt, 1+ on retries).
            max_withdrawal_retries: The maximum number of withdrawal retries
                configured for this game.

        Returns:
            A complete Proposal object representing the player's
            proposed change.
        """
        pass

    @abstractmethod
    def begin_discussion_turn(
        self,
        proposal: Proposal,
        game_state: GameState,
        rules: list[Rule],
    ) -> None:
        """
        Initialise the player's discussion context for a new round.

        This method is called by ``GameLoop._collect_discussions()`` before
        the player's first ``discuss()`` call each round.  It is the sole
        location where discussion history is reset/initialised.

        ``GameLoop._collect_discussions()`` skips this call on withdrawal-
        retry rounds when ``retain_discusser_history_on_retry`` is True,
        allowing non-proposing LLM players to retain accumulated context.

        Args:
            proposal: The proposal being discussed.
            game_state: The current state of the game.
            rules: The current list of all rules.
        """
        pass

    @abstractmethod
    def discuss(
        self,
        proposal: Proposal,
        game_state: GameState,
        rules: list[Rule],
    ) -> Discussion:
        """
        Provide discussion/commentary on a proposal.

        ``begin_discussion_turn()`` must be called before this method on
        the first discussion call of each round; this method must not
        perform any history initialisation itself.

        Args:
            proposal: The proposal being discussed.
            game_state: The current state of the game.
            rules: The current list of all rules.

        Returns:
            A Discussion object containing the player's discussion.
            If the player abstains, Discussion.text will be empty.
        """
        pass

    @abstractmethod
    def vote(
        self, proposal: Proposal, game_state: GameState, rules: list[Rule]
    ) -> Vote:
        """
        Cast a vote on a proposal.

        Args:
            proposal: The proposal being voted on.
            game_state: The current state of the game.
            rules: The current list of all rules.

        Returns:
            A complete Vote object representing the player's vote.
        """
        pass

    def note_withdrawal_for_retry(
        self,
        discussions: list[Discussion],
        withdrawal_attempt: int,
        max_withdrawal_retries: int,
    ) -> None:
        """Optional hook to preserve cumulative context for proposal pivots."""

        return None

    @abstractmethod
    def revise(
        self,
        proposal: Proposal,
        discussions: list[Discussion],
        game_state: GameState,
        rules: list[Rule],
    ) -> Proposal | None:
        """
        Allow the player to revise their proposal based on discussion.

        Args:
            proposal: The original proposal made by this player.
            discussions: A list of Discussion objects from all players.
            game_state: The current state of the game.
            rules: The current list of all rules.

        Returns:
            The (potentially) revised Proposal object,
            or None if the player chooses to withdraw the proposal.
        """
        pass
