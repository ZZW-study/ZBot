# 先安装：pip install rich
from rich.console import Console
import time

console = Console()

# 你的原版效果
with console.status("[dim green] 🤖 ZBot 正在思考...[/dim green]", spinner="dots"):
    # 这里放你真正的逻辑（思考、请求、处理）
    time.sleep(8)

console.print("[green]思考完成！[/green]")

