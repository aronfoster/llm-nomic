"""
MemoryManager: Utility for reading and writing LLM player memory files.

Memory files live under:
    games/<game-name>/memories/<Name>_MEMORY.md
"""

import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_MEMORIES_DIR = "memories"
_TRUNCATION_MARKER = "\n[MEMORY TRUNCATED]"

# ---------------------------------------------------------------------------
# Template builders
# ---------------------------------------------------------------------------

JUDGE_MEMORY_TEMPLATE = """\
# Judge's Private Memory

## Rule Interpretations & Precedents
(Record how ambiguous rules have been interpreted so rulings stay consistent.)

## Vetoed Proposals & Reasons
(Track vetoed proposals to identify patterns or rule gaps.)

## State Change Log
(Note flag or target_score changes and the rules that triggered them.)

## Notes on Rule Clarity
(Flag rules that have caused confusion; useful context for future veto
decisions.)
"""


def build_player_memory_template(
    player_name: str, other_names: list[str]
) -> str:
    """Build a player memory template listing every other participant.

    Args:
        player_name: The name of the player whose template this is.
        other_names: Names of all other players (excluding this player),
            plus "Judge" if an LLM judge is in play.  The caller is
            responsible for assembling this list.

    Returns:
        The rendered markdown template string.
    """
    per_player_lines = "\n".join(f"- {name}: " for name in other_names)
    return (
        f"# {player_name}'s Private Memory\n"
        "\n"
        "## Long-term Strategy & Goals\n"
        "\n"
        "## Observations of Other Players\n"
        f"{per_player_lines}\n"
        "\n"
        "## Key Rules & Tactics to Exploit\n"
        "\n"
        "## Recent Events & Plans\n"
        "\n"
        "## Private Notes\n"
    )


# ---------------------------------------------------------------------------
# MemoryManager
# ---------------------------------------------------------------------------


class MemoryManager:
    """Manages LLM memory files for a single game instance."""

    def __init__(self, game_dir: Path, max_characters: Optional[int]) -> None:
        """
        Args:
            game_dir: Root directory of the game instance.
            max_characters: Character cap applied on write.  ``None`` or
                ``0`` disables truncation.
        """
        self.game_dir = game_dir
        # Normalise 0 → None so downstream code only checks for None.
        self.max_characters: Optional[int] = (
            None
            if (max_characters is None or max_characters == 0)
            else max_characters
        )

    # ------------------------------------------------------------------
    # Path helper
    # ------------------------------------------------------------------

    def get_memory_path(self, name: str) -> Path:
        """Return the path for a named memory file.

        Args:
            name: Participant name, e.g. ``"Alice"`` or ``"Judge"``.

        Returns:
            ``memories/<name>_MEMORY.md`` relative to the game directory.
        """
        return self.game_dir / _MEMORIES_DIR / f"{name}_MEMORY.md"

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def create_memories_dir(self) -> None:
        """Create the ``memories/`` directory (idempotent)."""
        memories_dir = self.game_dir / _MEMORIES_DIR
        memories_dir.mkdir(parents=True, exist_ok=True)

    def read(self, name: str) -> str:
        """Return file content, or ``""`` if the file is missing or empty.

        Args:
            name: Participant name.

        Returns:
            Raw file content, or ``""`` when the file does not exist or
            contains no data.
        """
        path = self.get_memory_path(name)
        try:
            return path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return ""

    def write(self, name: str, content: str) -> None:
        """Write memory content, truncating if it exceeds ``max_characters``.

        Truncation is a dumb character slice:
        ``content[:max_characters] + "\\n[MEMORY TRUNCATED]"``

        Args:
            name: Participant name.
            content: Full memory content to write.
        """
        logger.debug("Memory pre-truncation content for %s: %s", name, content)

        if (
            self.max_characters is not None
            and len(content) > self.max_characters
        ):
            content = content[: self.max_characters] + _TRUNCATION_MARKER
            logger.info("Memory truncated for %s", name)

        self.get_memory_path(name).write_text(content, encoding="utf-8")
        logger.info("Memory saved for %s", name)

    def ensure_exists(self, name: str, template: str) -> None:
        """Create a memory file from ``template`` if missing or empty.

        Silently no-ops when the file already contains content.

        Args:
            name: Participant name.
            template: Template string written verbatim when the file is
                absent or empty.
        """
        path = self.get_memory_path(name)
        if not path.exists() or not path.read_text(encoding="utf-8").strip():
            path.write_text(template, encoding="utf-8")
