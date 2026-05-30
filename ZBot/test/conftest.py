"""测试基础设施：pytest fixtures 和自动重置逻辑。"""

import pytest

from ZBot.config.schema import Config


@pytest.fixture(autouse=True)
def _reset_config_singleton():
    """每个测试前重置 Config 单例，避免测试间状态污染。

    Config 通过 __new__ 实现进程级单例（schema.py:156-160），
    第一个测试实例化 Config 后，后续测试会复用同一实例，
    导致测试间互相影响。此 fixture 在每个测试前将 _instance 置 None，
    使下次 Config() 调用创建全新实例。
    """
    Config._instance = None
    yield
    Config._instance = None
