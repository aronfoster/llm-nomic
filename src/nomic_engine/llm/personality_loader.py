"""
Personality file loader for LLM player prompts.

Reads personality markdown files from the top-level ``personalities/``
directory, parses them into a dict of section name → content string, and
caches the result so each file is read at most once per process.

File format
-----------
Each personality file is a markdown document. Sections are delimited by
``## SECTION_NAME`` headers. Everything between two consecutive ``##``
headers (or between the last ``##`` header and EOF) is the content of
that section. Lines before the first ``##`` header (e.g. a ``#`` title
or HTML comments) are ignored.

Example::

    ## PERSONA
    You are {player_name}, ...

    ## STRATEGIC_GUIDANCE
    Prioritize proposals that ...

The ``{player_name}`` placeholder in PERSONA is left intact by the loader;
PromptBuilder resolves it at call time via ``.format(player_name=...)``.

Missing file behaviour
----------------------
If the requested personality file does not exist, a ``FileNotFoundError``
is raised with a descriptive message. The exception is intentionally
allowed to propagate up through turn execution.
"""

from pathlib import Path

# Resolve the personalities/ directory relative to this file's location.
# Layout: src/nomic_engine/llm/personality_loader.py  (this file)
#         personalities/                               (target directory)
# Four .parent calls walk up: llm/ -> nomic_engine/ -> src/ -> project root
_PERSONALITIES_DIR: Path = (
    Path(__file__).resolve().parent.parent.parent.parent / "personalities"
)

# Module-level cache: personality name -> parsed sections dict.
# Each file is read and parsed exactly once per process.
_cache: dict[str, dict[str, str]] = {}


def _parse_sections(text: str) -> dict[str, str]:
    """
    Parse markdown text into a dict of section name -> content string.

    Splits on ``## SECTION_NAME`` headers. Content before the first
    ``##`` header is discarded. Trailing whitespace is stripped from
    each section's content.

    Args:
        text: Raw file content as a string.

    Returns:
        Dict mapping uppercase section names to their content strings.
    """
    sections: dict[str, str] = {}
    current_section: str | None = None
    current_lines: list[str] = []

    for line in text.splitlines():
        if line.startswith("## "):
            # Save the previous section before starting a new one
            if current_section is not None:
                sections[current_section] = "\n".join(current_lines).strip()
            current_section = line[3:].strip()
            current_lines = []
        else:
            if current_section is not None:
                current_lines.append(line)

    # Save the final section
    if current_section is not None:
        sections[current_section] = "\n".join(current_lines).strip()

    return sections


def load_personality(name: str) -> dict[str, str]:
    """
    Load and return the parsed sections for a personality by name.

    The personality name must be normalized to lowercase before calling
    this function (enforced as a convention by ``create_game.py``).

    Results are cached after the first load; subsequent calls for the
    same name return the cached dict without re-reading the file.

    Args:
        name: Lowercase personality name (e.g. ``"machiavellian"``).

    Returns:
        Dict mapping section names (e.g. ``"PERSONA"``) to their
        content strings.

    Raises:
        FileNotFoundError: If ``personalities/{name}.md`` does not exist.
            The message includes the expected path and a hint to check
            the ``personalities/`` directory for available options.
    """
    if name in _cache:
        return _cache[name]

    path = _PERSONALITIES_DIR / f"{name}.md"
    if not path.exists():
        available = (
            sorted(p.stem for p in _PERSONALITIES_DIR.glob("*.md"))
            if _PERSONALITIES_DIR.exists()
            else []
        )
        available_str = (
            ", ".join(f"'{p}'" for p in available)
            if available
            else "none found"
        )
        raise FileNotFoundError(
            f"Personality file not found for '{name}'. "
            f"Expected: {path}. "
            f"Available personalities: {available_str}."
        )

    text = path.read_text(encoding="utf-8")
    sections = _parse_sections(text)
    _cache[name] = sections
    return sections
