"""
Tests for MemoryManager.
"""

import tempfile
from pathlib import Path

import pytest

from src.nomic_engine.memory.memory_manager import MemoryManager

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mem_dir():
    """Temporary game directory with a pre-created memories/ sub-dir."""
    with tempfile.TemporaryDirectory() as tmpdir:
        game_dir = Path(tmpdir)
        (game_dir / "memories").mkdir()
        yield game_dir


def make_manager(game_dir: Path, max_chars: int | None) -> MemoryManager:
    return MemoryManager(game_dir, max_chars)


# ---------------------------------------------------------------------------
# get_memory_path
# ---------------------------------------------------------------------------


def test_get_memory_path_returns_correct_path(mem_dir):
    mm = make_manager(mem_dir, None)
    expected = mem_dir / "memories" / "Alice_MEMORY.md"
    assert mm.get_memory_path("Alice") == expected


def test_get_memory_path_judge(mem_dir):
    mm = make_manager(mem_dir, None)
    assert (
        mm.get_memory_path("Judge") == mem_dir / "memories" / "Judge_MEMORY.md"
    )


# ---------------------------------------------------------------------------
# create_memories_dir
# ---------------------------------------------------------------------------


def test_create_memories_dir_creates_directory():
    with tempfile.TemporaryDirectory() as tmpdir:
        game_dir = Path(tmpdir)
        mm = make_manager(game_dir, None)
        mm.create_memories_dir()
        assert (game_dir / "memories").is_dir()


def test_create_memories_dir_is_idempotent(mem_dir):
    mm = make_manager(mem_dir, None)
    mm.create_memories_dir()  # already exists – should not raise
    assert (mem_dir / "memories").is_dir()


# ---------------------------------------------------------------------------
# read
# ---------------------------------------------------------------------------


def test_read_returns_empty_string_when_file_missing(mem_dir):
    mm = make_manager(mem_dir, None)
    assert mm.read("Alice") == ""


def test_read_returns_empty_string_when_file_is_empty(mem_dir):
    (mem_dir / "memories" / "Alice_MEMORY.md").write_text("", encoding="utf-8")
    mm = make_manager(mem_dir, None)
    assert mm.read("Alice") == ""


def test_read_returns_file_content(mem_dir):
    content = "# Alice's Memory\n\nSome notes."
    (mem_dir / "memories" / "Alice_MEMORY.md").write_text(
        content, encoding="utf-8"
    )
    mm = make_manager(mem_dir, None)
    assert mm.read("Alice") == content


# ---------------------------------------------------------------------------
# write – truncation
# ---------------------------------------------------------------------------


def test_write_truncates_at_exactly_max_characters(mem_dir):
    mm = make_manager(mem_dir, max_chars=10)
    mm.write("Alice", "Hello World!")
    result = (mem_dir / "memories" / "Alice_MEMORY.md").read_text(
        encoding="utf-8"
    )
    # First 10 chars + marker
    assert result == "Hello Worl\n[MEMORY TRUNCATED]"


def test_write_does_not_truncate_when_content_at_limit(mem_dir):
    content = "A" * 10
    mm = make_manager(mem_dir, max_chars=10)
    mm.write("Alice", content)
    result = (mem_dir / "memories" / "Alice_MEMORY.md").read_text(
        encoding="utf-8"
    )
    assert result == content
    assert "[MEMORY TRUNCATED]" not in result


def test_write_does_not_truncate_when_content_below_limit(mem_dir):
    content = "Short"
    mm = make_manager(mem_dir, max_chars=100)
    mm.write("Alice", content)
    result = (mem_dir / "memories" / "Alice_MEMORY.md").read_text(
        encoding="utf-8"
    )
    assert result == content
    assert "[MEMORY TRUNCATED]" not in result


def test_write_does_not_truncate_when_max_characters_is_none(mem_dir):
    content = "X" * 100_000
    mm = make_manager(mem_dir, max_chars=None)
    mm.write("Alice", content)
    result = (mem_dir / "memories" / "Alice_MEMORY.md").read_text(
        encoding="utf-8"
    )
    assert result == content
    assert "[MEMORY TRUNCATED]" not in result


def test_write_does_not_truncate_when_max_characters_is_zero(mem_dir):
    """max_characters=0 is normalised to None (unlimited)."""
    content = "Y" * 50_000
    mm = make_manager(mem_dir, max_chars=0)
    mm.write("Alice", content)
    result = (mem_dir / "memories" / "Alice_MEMORY.md").read_text(
        encoding="utf-8"
    )
    assert result == content
    assert "[MEMORY TRUNCATED]" not in result


def test_write_truncation_marker_appended_after_slice(mem_dir):
    mm = make_manager(mem_dir, max_chars=5)
    mm.write("Alice", "Hello World")
    result = (mem_dir / "memories" / "Alice_MEMORY.md").read_text(
        encoding="utf-8"
    )
    assert result.startswith("Hello")
    assert result.endswith("[MEMORY TRUNCATED]")


# ---------------------------------------------------------------------------
# ensure_exists
# ---------------------------------------------------------------------------


def test_ensure_exists_creates_file_when_missing(mem_dir):
    template = "# Template\n"
    mm = make_manager(mem_dir, None)
    mm.ensure_exists("Alice", template)
    result = (mem_dir / "memories" / "Alice_MEMORY.md").read_text(
        encoding="utf-8"
    )
    assert result == template


def test_ensure_exists_creates_file_when_empty(mem_dir):
    template = "# Template\n"
    path = mem_dir / "memories" / "Alice_MEMORY.md"
    path.write_text("", encoding="utf-8")
    mm = make_manager(mem_dir, None)
    mm.ensure_exists("Alice", template)
    assert path.read_text(encoding="utf-8") == template


def test_ensure_exists_creates_file_when_whitespace_only(mem_dir):
    template = "# Template\n"
    path = mem_dir / "memories" / "Alice_MEMORY.md"
    path.write_text("   \n  ", encoding="utf-8")
    mm = make_manager(mem_dir, None)
    mm.ensure_exists("Alice", template)
    assert path.read_text(encoding="utf-8") == template


def test_ensure_exists_does_not_overwrite_existing_content(mem_dir):
    original = "# Alice's memory\n\nExisting notes."
    path = mem_dir / "memories" / "Alice_MEMORY.md"
    path.write_text(original, encoding="utf-8")
    mm = make_manager(mem_dir, None)
    mm.ensure_exists("Alice", "# New Template\n")
    assert path.read_text(encoding="utf-8") == original
