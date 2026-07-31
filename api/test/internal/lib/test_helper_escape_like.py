from internal.lib.helper import escape_like_pattern


def test_escape_like_pattern_should_escape_percent():
    assert escape_like_pattern("50%") == "50\\%"


def test_escape_like_pattern_should_escape_underscore():
    assert escape_like_pattern("a_b") == "a\\_b"


def test_escape_like_pattern_should_escape_backslash_first():
    assert escape_like_pattern("a\\b%") == "a\\\\b\\%"


def test_escape_like_pattern_should_handle_none_and_empty():
    assert escape_like_pattern(None) == ""
    assert escape_like_pattern("") == ""


def test_escape_like_pattern_should_leave_plain_text_untouched():
    assert escape_like_pattern("普通文本查询") == "普通文本查询"
