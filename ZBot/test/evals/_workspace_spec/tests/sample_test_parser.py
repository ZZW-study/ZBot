"""parser 工具函数的单元测试。"""

from src.parser import parse_kv_lines, parse_json_safe, split_sections


def test_parse_kv_lines_basic():
    text = "name: alice\nage: 30\n# comment\ncity: paris"
    assert parse_kv_lines(text) == {"name": "alice", "age": "30", "city": "paris"}


def test_parse_kv_lines_empty():
    assert parse_kv_lines("") == {}


def test_parse_json_safe_dict():
    assert parse_json_safe('{"a": 1, "b": [2, 3]}') == {"a": 1, "b": [2, 3]}


def test_parse_json_safe_invalid_returns_empty():
    assert parse_json_safe("not json") == {}


def test_split_sections_basic():
    text = "[a]\n1\n2\n[b]\n3"
    sections = split_sections(text)
    assert sections["a"] == ["1", "2"]
    assert sections["b"] == ["3"]