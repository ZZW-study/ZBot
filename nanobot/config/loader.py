"""
配置加载工具模块
作用：专门管理 Nanobot 的配置文件（config.json）
包含：读取配置、保存配置、获取配置路径、兼容旧配置格式 四大核心功能
"""
import json
from pathlib import Path
from nanobot.config.schema import Config

# 全局变量：存储当前的配置文件路径
# 作用：支持多开 Nanobot 实例时，每个实例用不同的配置文件（默认是 None，用系统默认路径）
_current_config_path: Path | None = None


def get_path_config() ->Path:
    """
    获取当前使用的配置文件路径
    返回：最终要使用的 config.json 路径
    规则：优先用手动设置的路径 → 没有就用系统默认路径
    """
    if _current_config_path:
        return _current_config_path
    
    return Path.home() /".nanobot"/"config.json"


def load_config(config_path: Path | None = None) ->Config:
    """
    从文件加载配置 → 生成配置对象（程序运行用的就是这个对象）
    返回：Config 配置对象（包含 WhatsApp、AI、工具等所有设置）
    """
    path = config_path or get_path_config()

    # 判断：如果配置文件真的存在（电脑里有这个 config.json）
    if path.exists():
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            return Config.model_validate(data)
        except (json.JSONDecodeError,ValueError) as e:
            print(f"警告：从{path}加载配置失败:{e}")
            print("使用错误的配置")

    # 如果文件不存在 / 加载失败 → 直接返回【默认配置对象】
    return Config()


def save_config(config: Config,config_path: Path | None = None) ->None:
    """
    把程序里的配置对象 → 保存到电脑的 config.json 文件
    参数：config = 要保存的配置对象；config_path = 保存路径（可选）
    作用：修改配置后，永久写入文件，下次启动还能用
    """
    path = config_path or get_path_config()
    path.parent.mkdir(parents=True,exist_ok=True)

    data = config.model_dump(by_alias=True)

    with open(path,mode = "w",encoding="utf-8") as f:
        json.dump(data,f,indent=2,ensure_ascii=False)   # 缩进 2 个空格,关闭ascii码强制转换




