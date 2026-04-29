"""配置文件加载与保存工具。"""

from __future__ import annotations              
import json  
from pathlib import Path  
from pydantic import ValidationError            
from ZBot.config.paths import get_config_path   
from ZBot.config.schema import Config          


def load_config(config_path: Path | None = None) -> Config | None:
    """
    从磁盘文件中加载配置，若配置缺失，可以model_validate可以补全。
    """
    # 确定配置文件路径
    path = config_path or get_config_path()

    # ========== 读取磁盘配置 ==========
    try:
        with open(path, encoding="utf-8") as file:
            data = json.load(file)                
        if isinstance(data, dict):
            # ========== 解析配置数据 ==========
            config = Config.model_validate(data)  
            return config
        else:
            raise ValueError(f"警告：配置文件 {path} 的内容必须是 JSON 格式，请重新设置。")
    except (json.JSONDecodeError, OSError, ValidationError, ValueError) as exc:
        print(f"警告：读取配置文件 {path} 失败：{exc}")
        print("无法解析的配置项将回退到默认值。")

    return None

def save_config(config: Config, config_path: Path | None = None) -> None:
    """
    把配置对象写回磁盘。
    """
    from ZBot.utils.helpers import ensure_dir

    path = config_path or get_config_path()
    ensure_dir(path.parent)  
    
    # 将 Config 对象转换为字典并写入 JSON 文件
    data = config.model_dump(by_alias=True) 
    path.write_text(json.dumps(data, indent=4, ensure_ascii=False), encoding="utf-8")
