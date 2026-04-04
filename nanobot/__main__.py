"""nanobot 的程序总入口。

执行 `python -m nanobot` 时，Python 会先进入这个文件，
再转交给真正的 CLI 模块去解析命令。
"""

from nanobot.cli.commands import app


if __name__ == "__main__":
    app()
