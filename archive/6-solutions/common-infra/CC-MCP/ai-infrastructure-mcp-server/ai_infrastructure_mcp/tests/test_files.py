"""Tests for file access tools."""

import ai_infrastructure_mcp.tools.files as files


def test_head_file_basic(monkeypatch):
    """Test basic head_file functionality."""
    sample = "line 1\nline 2\nline 3"  # No trailing newline

    def fake_run(cmd: str):
        assert "head -n 3" in cmd
        assert "/test/file" in cmd
        return sample

    monkeypatch.setattr(files, "run_login_command", fake_run)

    result = files.head_file("/test/file", offset=0, length=3)
    assert result["version"] == 1
    assert result["success"] is True
    assert result["path"] == "/test/file"
    assert result["offset"] == 0
    assert result["length"] == 3
    assert result["line_count"] == 3
    assert result["lines"] == ["line 1", "line 2", "line 3"]
    assert result["error"] is None


def test_head_file_with_offset(monkeypatch):
    """Test head_file with offset."""
    sample = "line 3\nline 4"  # No trailing newline

    def fake_run(cmd: str):
        assert "tail -n +3" in cmd and "head -n 2" in cmd
        assert "/test/file" in cmd
        return sample

    monkeypatch.setattr(files, "run_login_command", fake_run)

    result = files.head_file("/test/file", offset=2, length=2)
    assert result["version"] == 1
    assert result["success"] is True
    assert result["line_count"] == 2
    assert result["lines"] == ["line 3", "line 4"]


def test_head_file_not_found(monkeypatch):
    """Test head_file with non-existent file."""

    def fake_run(cmd: str):
        return "stdout content\n[stderr]\nhead: cannot open '/nonexistent' for reading: No such file or directory\n"

    monkeypatch.setattr(files, "run_login_command", fake_run)

    result = files.head_file("/nonexistent")
    assert result["version"] == 1
    assert result["success"] is False
    assert "File not found" in result["error"]
    assert result["line_count"] == 0
    assert result["lines"] == []


def test_head_file_invalid_params():
    """Test head_file with invalid parameters."""
    result = files.head_file("/test/file", length=0)
    assert result["success"] is False
    assert "Length must be greater than 0" in result["error"]

    result = files.head_file("/test/file", offset=-1)
    assert result["success"] is False
    assert "Offset must be non-negative" in result["error"]


def test_tail_file_basic(monkeypatch):
    """Test basic tail_file functionality."""
    sample = "line 3\nline 4\nline 5\n"

    def fake_run(cmd: str):
        assert "tail -n 3" in cmd
        assert "/test/file" in cmd
        return sample

    monkeypatch.setattr(files, "run_login_command", fake_run)

    result = files.tail_file("/test/file", offset=0, length=3)
    assert result["version"] == 1
    assert result["success"] is True
    assert result["path"] == "/test/file"
    assert result["offset"] == 0
    assert result["length"] == 3
    assert result["line_count"] == 3
    assert result["lines"] == ["line 3", "line 4", "line 5"]
    assert result["error"] is None


def test_tail_file_with_offset(monkeypatch):
    """Test tail_file with offset."""
    call_count = 0

    def fake_run(cmd: str):
        nonlocal call_count
        call_count += 1

        if call_count == 1:
            # First call is wc -l
            assert "wc -l <" in cmd
            return "10\n"
        else:
            # Second call is sed
            assert "sed -n" in cmd
            assert "7,8p" in cmd  # lines 7-8 (10 - 2 - 2 + 1 = 7, 10 - 2 = 8)
            return "line 7\nline 8\n"

    monkeypatch.setattr(files, "run_login_command", fake_run)

    result = files.tail_file("/test/file", offset=2, length=2)
    assert result["version"] == 1
    assert result["success"] is True
    assert result["line_count"] == 2
    assert result["lines"] == ["line 7", "line 8"]


def test_tail_file_offset_too_large(monkeypatch):
    """Test tail_file with offset larger than file."""

    def fake_run(cmd: str):
        if "wc -l" in cmd:
            return "5\n"
        return ""

    monkeypatch.setattr(files, "run_login_command", fake_run)

    result = files.tail_file("/test/file", offset=10, length=2)
    assert result["version"] == 1
    assert result["success"] is True
    assert result["line_count"] == 0
    assert result["lines"] == []


def test_count_file_lines(monkeypatch):
    """Test count_file with lines mode."""

    def fake_run(cmd: str):
        assert "wc -l <" in cmd
        assert "/test/file" in cmd
        return "42\n"

    monkeypatch.setattr(files, "run_login_command", fake_run)

    result = files.count_file("/test/file", mode="lines")
    assert result["version"] == 1
    assert result["success"] is True
    assert result["path"] == "/test/file"
    assert result["mode"] == "lines"
    assert result["count"] == 42
    assert result["error"] is None


def test_count_file_bytes(monkeypatch):
    """Test count_file with bytes mode."""

    def fake_run(cmd: str):
        assert "wc -c <" in cmd
        assert "/test/file" in cmd
        return "1024\n"

    monkeypatch.setattr(files, "run_login_command", fake_run)

    result = files.count_file("/test/file", mode="bytes")
    assert result["version"] == 1
    assert result["success"] is True
    assert result["mode"] == "bytes"
    assert result["count"] == 1024


def test_count_file_invalid_mode():
    """Test count_file with invalid mode."""
    result = files.count_file("/test/file", mode="invalid")
    assert result["success"] is False
    assert "Mode must be 'lines' or 'bytes'" in result["error"]


def test_count_file_not_found(monkeypatch):
    """Test count_file with non-existent file."""

    def fake_run(cmd: str):
        return "output\n[stderr]\nwc: '/nonexistent': No such file or directory\n"

    monkeypatch.setattr(files, "run_login_command", fake_run)

    result = files.count_file("/nonexistent")
    assert result["success"] is False
    assert "File not found" in result["error"]


def test_search_file_basic(monkeypatch):
    """Test basic search_file functionality."""
    grep_output = "3:found pattern here\n5:another pattern match\n"

    def fake_run(cmd: str):
        assert "grep -n" in cmd
        assert "pattern" in cmd
        assert "/test/file" in cmd
        return grep_output

    monkeypatch.setattr(files, "run_login_command", fake_run)

    result = files.search_file("/test/file", "pattern")
    assert result["version"] == 1
    assert result["success"] is True
    assert result["path"] == "/test/file"
    assert result["pattern"] == "pattern"
    assert result["before"] == 0
    assert result["after"] == 0
    assert result["match_count"] == 2

    matches = result["matches"]
    assert len(matches) == 2
    assert matches[0]["line_number"] == 3
    assert matches[0]["line"] == "found pattern here"
    assert matches[1]["line_number"] == 5
    assert matches[1]["line"] == "another pattern match"


def test_search_file_with_context(monkeypatch):
    """Test search_file with before/after context."""
    grep_output = """2-before line
3:match line
4-after line
--
6-another before
7:another match
8-another after"""

    def fake_run(cmd: str):
        assert "grep -n" in cmd
        assert "-B 1" in cmd
        assert "-A 1" in cmd
        assert "pattern" in cmd
        return grep_output

    monkeypatch.setattr(files, "run_login_command", fake_run)

    result = files.search_file("/test/file", "pattern", before=1, after=1)
    assert result["version"] == 1
    assert result["success"] is True
    assert result["match_count"] == 2

    matches = result["matches"]
    assert len(matches) == 2

    # First match
    assert matches[0]["line_number"] == 3
    assert matches[0]["line"] == "match line"
    assert len(matches[0]["context_before"]) == 1
    assert matches[0]["context_before"][0]["line_number"] == 2
    assert matches[0]["context_before"][0]["line"] == "before line"
    assert len(matches[0]["context_after"]) == 1
    assert matches[0]["context_after"][0]["line_number"] == 4
    assert matches[0]["context_after"][0]["line"] == "after line"

    # Second match
    assert matches[1]["line_number"] == 7
    assert matches[1]["line"] == "another match"


def test_search_file_no_matches(monkeypatch):
    """Test search_file with no matches."""

    def fake_run(cmd: str):
        return ""  # No output means no matches

    monkeypatch.setattr(files, "run_login_command", fake_run)

    result = files.search_file("/test/file", "nonexistent")
    assert result["version"] == 1
    assert result["success"] is True
    assert result["match_count"] == 0
    assert result["matches"] == []


def test_search_file_not_found(monkeypatch):
    """Test search_file with non-existent file."""

    def fake_run(cmd: str):
        return "output\n[stderr]\ngrep: /nonexistent: No such file or directory\n"

    monkeypatch.setattr(files, "run_login_command", fake_run)

    result = files.search_file("/nonexistent", "pattern")
    assert result["success"] is False
    assert "File not found" in result["error"]


def test_search_file_invalid_params():
    """Test search_file with invalid parameters."""
    result = files.search_file("/test/file", "pattern", max_matches=0)
    assert result["success"] is False
    assert "max_matches must be greater than 0" in result["error"]

    result = files.search_file("/test/file", "pattern", before=-1)
    assert result["success"] is False
    assert "before and after must be non-negative" in result["error"]

    result = files.search_file("/test/file", "pattern", after=-1)
    assert result["success"] is False
    assert "before and after must be non-negative" in result["error"]


def test_search_file_max_matches(monkeypatch):
    """Test search_file with max_matches limit."""

    def fake_run(cmd: str):
        assert "-m 5" in cmd  # Should limit to 5 matches
        return "1:match\n2:match\n3:match\n"

    monkeypatch.setattr(files, "run_login_command", fake_run)

    result = files.search_file("/test/file", "pattern", max_matches=5)
    assert result["success"] is True
    assert result["max_matches"] == 5


def test_empty_file_handling(monkeypatch):
    """Test handling of empty files."""

    def fake_run(cmd: str):
        return ""  # Empty output

    monkeypatch.setattr(files, "run_login_command", fake_run)

    # Test head_file with empty file
    result = files.head_file("/empty/file")
    assert result["success"] is True
    assert result["line_count"] == 0
    assert result["lines"] == []

    # Test search_file with empty file
    result = files.search_file("/empty/file", "pattern")
    assert result["success"] is True
    assert result["match_count"] == 0
    assert result["matches"] == []


def test_file_path_escaping(monkeypatch):
    """Test that file paths are properly escaped for shell safety."""

    def fake_run(cmd: str):
        # Verify that special characters in path are quoted
        assert "'file with spaces & symbols.txt'" in cmd
        return "test output\n"

    monkeypatch.setattr(files, "run_login_command", fake_run)

    result = files.head_file("file with spaces & symbols.txt")
    assert result["success"] is True


def test_pattern_escaping(monkeypatch):
    """Test that search patterns are properly escaped for shell safety."""

    def fake_run(cmd: str):
        # Verify that special characters in pattern are quoted
        assert "'special $pattern [with] chars'" in cmd
        return ""

    monkeypatch.setattr(files, "run_login_command", fake_run)

    result = files.search_file("/test/file", "special $pattern [with] chars")
    assert result["success"] is True
