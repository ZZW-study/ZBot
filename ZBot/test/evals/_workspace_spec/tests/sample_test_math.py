"""简单的数学函数测试，用于演示 workflow 任务（让 Agent 跑 pytest）。"""


def add(a, b):
    return a + b


def mul(a, b):
    return a * b


def sub(a, b):
    return a - b


def test_add():
    assert add(1, 2) == 3


def test_mul():
    assert mul(2, 3) == 6


def test_sub_negative():
    assert sub(2, 5) == -3