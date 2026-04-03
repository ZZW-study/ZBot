#!/usr/bin/env python3
"""
技能初始化工具 - 通过模板创建新技能

用法:
    init_skill.py <技能名称> --path <路径> [--resources scripts,references,assets] [--examples]

示例:
    init_skill.py my-new-skill --path skills/public
    init_skill.py my-new-skill --path skills/public --resources scripts,references
    init_skill.py my-api-helper --path skills/private --resources scripts --examples
    init_skill.py custom-skill --path /custom/location
"""

# 导入依赖库
import argparse       # 命令行参数解析
import re             # 正则表达式，用于名称格式化
import sys            # 系统操作，用于退出程序
from pathlib import Path  # 面向对象的文件路径处理

# ===================== 常量定义 =====================
# 技能名称最大长度限制
MAX_SKILL_NAME_LENGTH = 64
# 允许创建的资源目录类型
ALLOWED_RESOURCES = {"scripts", "references", "assets"}

# ===================== 模板字符串 =====================
# 技能主文档模板 (SKILL.md)
SKILL_TEMPLATE = """---
name: {skill_name}
description: [待完善：详细说明该技能的功能、使用场景，明确触发该技能的具体场景、文件类型或任务]
---

# {skill_title}

## 概述

[待完善：用1-2句话说明该技能能实现什么功能]

## 技能结构规划

[待完善：选择最适合该技能的结构，常用模式：

**1. 工作流模式**（适用于顺序执行的流程）
- 适合有清晰步骤的操作
- 示例：DOCX技能 → 工作流决策树 → 读取 → 创建 → 编辑
- 结构：## 概述 -> ## 工作流决策树 -> ## 步骤1 -> ## 步骤2...

**2. 任务模式**（适用于工具集合）
- 适合提供多种操作/功能的技能
- 示例：PDF技能 → 快速开始 → 合并PDF → 拆分PDF → 提取文本
- 结构：## 概述 -> ## 快速开始 -> ## 任务分类1 -> ## 任务分类2...

**3. 参考/规范模式**（适用于标准或说明文档）
- 适合品牌规范、编码标准、需求说明
- 示例：品牌风格 → 品牌规范 → 颜色 → 字体 → 功能
- 结构：## 概述 -> ## 规范 -> ## 规格 -> ## 使用方法...

**4. 功能模式**（适用于集成系统）
- 适合提供多个关联功能的技能
- 示例：项目管理 → 核心功能 → 功能列表
- 结构：## 概述 -> ## 核心功能 -> ### 1. 功能 -> ### 2. 功能...

可混合使用多种模式，大部分技能会组合使用（例如：以任务模式为基础，复杂操作增加工作流说明）。

完成后删除此"技能结构规划"章节，仅作为指导使用。]

## [待完善：根据选择的结构，替换为第一个主章节]

[待完善：在此添加内容，参考现有技能示例：
- 技术技能：添加代码示例
- 复杂工作流：添加决策树
- 实用技能：添加真实用户请求案例
- 按需引用脚本/模板/参考文件]

## 资源文件（可选）

仅创建技能需要的资源目录，无需资源可删除此章节。

### scripts/
可直接运行的可执行代码（Python/Bash等），用于执行特定操作。

**其他技能示例：**
- PDF技能：`fill_fillable_fields.py`、`extract_form_field_info.py` - PDF处理工具
- DOCX技能：`document.py`、`utilities.py` - 文档处理Python模块

**适用场景：** Python脚本、Shell脚本、自动化/数据处理/专用操作的可执行代码。

**注意：** 脚本可直接执行，不会加载到上下文，但Codex可读取并修改。

### references/
用于加载到上下文的文档和参考资料，指导Codex的工作流程。

**其他技能示例：**
- 项目管理：`communication.md`、`context_building.md` - 详细工作流指南
- BigQuery：API参考文档、查询示例
- 财务：Schema文档、公司政策

**适用场景：** 深度文档、API参考、数据库结构、综合指南、Codex工作所需的详细信息。

### assets/
不加载到上下文，仅用于Codex输出结果的文件资源。

**其他技能示例：**
- 品牌风格：PPT模板、Logo文件
- 前端构建：HTML/React项目模板
- 字体：字体文件(.ttf, .woff2)

**适用场景：** 模板、脚手架、文档模板、图片、图标、字体或最终输出需要的文件。

---

**不是所有技能都需要这三类资源。**
"""

# 示例脚本模板
EXAMPLE_SCRIPT = '''#!/usr/bin/env python3
"""
{skill_name} 技能的示例辅助脚本

这是一个可直接运行的占位脚本，
请替换为实际功能代码，无需使用可删除。

其他技能的真实示例：
- pdf/scripts/fill_fillable_fields.py - 填充PDF表单字段
- pdf/scripts/convert_pdf_to_images.py - PDF页面转图片
"""

def main():
    print(f"这是 {skill_name} 的示例脚本")
    # 待完善：在此添加实际脚本逻辑
    # 可用于数据处理、文件转换、API调用等

if __name__ == "__main__":
    main()
'''

# 示例参考文档模板
EXAMPLE_REFERENCE = """# {skill_title} 参考文档

这是详细参考文档的占位文件，
请替换为实际参考内容，无需使用可删除。

其他技能的真实参考文档：
- product-management/references/communication.md - 状态更新综合指南
- product-management/references/context_building.md - 上下文收集深度指南
- bigquery/references/ - API参考和查询示例

## 参考文档适用场景

参考文档适合：
- 完整的API文档
- 详细的工作流指南
- 复杂的多步骤流程
- 主SKILL.md中过长的内容
- 特定场景才需要的内容

## 结构建议

### API参考示例
- 概述
- 认证方式
- 带示例的接口
- 错误码
- 频率限制

### 工作流指南示例
- 前置条件
- 分步说明
- 通用模式
- 故障排除
- 最佳实践
"""

# 示例资源文件模板
EXAMPLE_ASSET = """# 示例资源文件

此文件为资源文件的占位说明，
请替换为实际资源文件（模板、图片、字体等），无需使用可删除。

资源文件**不会**加载到上下文，仅用于Codex生成输出结果。

其他技能的资源文件示例：
- 品牌规范：logo.png、幻灯片模板.pptx
- 前端构建：hello-world/ HTML/React脚手架
- 字体：custom-font.ttf、font-family.woff2
- 数据：sample_data.csv、test_dataset.json

## 常用资源类型

- 模板：.pptx、.docx、项目脚手架
- 图片：.png、.jpg、.svg、.gif
- 字体：.ttf、.otf、.woff、.woff2
- 脚手架代码：项目目录、初始文件
- 图标：.ico、.svg
- 数据文件：.csv、.json、.xml、.yaml

注意：这是文本占位文件，实际资源可以是任意文件类型。
"""

# ===================== 核心功能函数 =====================
def normalize_skill_name(skill_name):
    """
    标准化技能名称：转为小写短横线格式
    参数：skill_name - 原始技能名称
    返回：格式化后的标准名称
    """
    # 去除首尾空格并转为小写
    normalized = skill_name.strip().lower()
    # 将非字母数字字符替换为短横线
    normalized = re.sub(r"[^a-z0-9]+", "-", normalized)
    # 去除首尾短横线
    normalized = normalized.strip("-")
    # 合并连续的短横线
    normalized = re.sub(r"-{2,}", "-", normalized)
    return normalized


def title_case_skill_name(skill_name):
    """
    将短横线格式的名称转为标题格式（用于展示）
    参数：skill_name - 标准化后的技能名称
    返回：首字母大写的标题格式名称
    """
    return " ".join(word.capitalize() for word in skill_name.split("-"))


def parse_resources(raw_resources):
    """
    解析命令行传入的资源参数，校验合法性
    参数：raw_resources - 逗号分隔的资源字符串
    返回：去重后的合法资源列表
    """
    if not raw_resources:
        return []
    
    # 分割并清理字符串
    resources = [item.strip() for item in raw_resources.split(",") if item.strip()]
    # 校验无效资源类型
    invalid = sorted({item for item in resources if item not in ALLOWED_RESOURCES})
    
    if invalid:
        allowed = ", ".join(sorted(ALLOWED_RESOURCES))
        print(f"[错误] 未知的资源类型：{', '.join(invalid)}")
        print(f"   支持的类型：{allowed}")
        sys.exit(1)
    
    # 去重处理
    deduped = []
    seen = set()
    for resource in resources:
        if resource not in seen:
            deduped.append(resource)
            seen.add(resource)
    return deduped


def create_resource_dirs(skill_dir, skill_name, skill_title, resources, include_examples):
    """
    创建资源目录（scripts/references/assets）
    参数：
        skill_dir - 技能根目录
        skill_name - 标准技能名称
        skill_title - 标题格式名称
        resources - 要创建的资源列表
        include_examples - 是否创建示例文件
    """
    for resource in resources:
        resource_dir = skill_dir / resource
        resource_dir.mkdir(exist_ok=True)
        
        # 根据资源类型创建示例文件
        if resource == "scripts":
            if include_examples:
                example_script = resource_dir / "example.py"
                example_script.write_text(EXAMPLE_SCRIPT.format(skill_name=skill_name))
                example_script.chmod(0o755)  # 设置可执行权限
                print("[成功] 创建 scripts/example.py")
            else:
                print("[成功] 创建 scripts/")
                
        elif resource == "references":
            if include_examples:
                example_reference = resource_dir / "api_reference.md"
                example_reference.write_text(EXAMPLE_REFERENCE.format(skill_title=skill_title))
                print("[成功] 创建 references/api_reference.md")
            else:
                print("[成功] 创建 references/")
                
        elif resource == "assets":
            if include_examples:
                example_asset = resource_dir / "example_asset.txt"
                example_asset.write_text(EXAMPLE_ASSET)
                print("[成功] 创建 assets/example_asset.txt")
            else:
                print("[成功] 创建 assets/")


def init_skill(skill_name, path, resources, include_examples):
    """
    初始化新技能：创建目录 + SKILL.md + 资源目录
    参数：
        skill_name - 标准化技能名称
        path - 技能存放路径
        resources - 资源目录列表
        include_examples - 是否包含示例文件
    返回：技能目录路径（失败返回None）
    """
    # 拼接技能完整路径
    skill_dir = Path(path).resolve() / skill_name

    # 校验目录是否已存在
    if skill_dir.exists():
        print(f"[错误] 技能目录已存在：{skill_dir}")
        return None

    # 创建技能根目录
    try:
        skill_dir.mkdir(parents=True, exist_ok=False)
        print(f"[成功] 创建技能目录：{skill_dir}")
    except Exception as e:
        print(f"[错误] 创建目录失败：{e}")
        return None

    # 生成并写入SKILL.md文件
    skill_title = title_case_skill_name(skill_name)
    skill_content = SKILL_TEMPLATE.format(skill_name=skill_name, skill_title=skill_title)

    skill_md_path = skill_dir / "SKILL.md"
    try:
        skill_md_path.write_text(skill_content)
        print("[成功] 创建 SKILL.md")
    except Exception as e:
        print(f"[错误] 创建 SKILL.md 失败：{e}")
        return None

    # 创建资源目录
    if resources:
        try:
            create_resource_dirs(skill_dir, skill_name, skill_title, resources, include_examples)
        except Exception as e:
            print(f"[错误] 创建资源目录失败：{e}")
            return None

    # 输出后续操作指引
    print(f"\n[成功] 技能 '{skill_name}' 初始化完成，路径：{skill_dir}")
    print("\n后续步骤：")
    print("1. 编辑 SKILL.md，完善所有待办事项和描述")
    if resources:
        if include_examples:
            print("2. 自定义或删除 scripts/references/assets 中的示例文件")
        else:
            print("2. 按需向资源目录添加文件")
    else:
        print("2. 按需创建资源目录（scripts/references/assets）")
    print("3. 完成后运行校验工具检查技能结构")

    return skill_dir


def main():
    """主函数：解析参数 → 校验 → 初始化技能"""
    # 初始化命令行参数解析器
    parser = argparse.ArgumentParser(
        description="创建新技能目录并生成SKILL.md模板",
    )
    # 必选参数：技能名称
    parser.add_argument("skill_name", help="技能名称（自动格式化为短横线格式）")
    # 必选参数：输出路径
    parser.add_argument("--path", required=True, help="技能的输出目录")
    # 可选参数：资源目录
    parser.add_argument(
        "--resources",
        default="",
        help="逗号分隔的资源类型：scripts,references,assets",
    )
    # 可选参数：创建示例文件
    parser.add_argument(
        "--examples",
        action="store_true",
        help="在资源目录中创建示例文件",
    )
    
    # 解析命令行参数
    args = parser.parse_args()

    # 标准化技能名称
    raw_skill_name = args.skill_name
    skill_name = normalize_skill_name(raw_skill_name)
    
    # 校验技能名称合法性
    if not skill_name:
        print("[错误] 技能名称必须包含至少一个字母或数字")
        sys.exit(1)
    if len(skill_name) > MAX_SKILL_NAME_LENGTH:
        print(
            f"[错误] 技能名称 '{skill_name}' 过长（{len(skill_name)}字符）"
            f"最大限制：{MAX_SKILL_NAME_LENGTH}字符"
        )
        sys.exit(1)
        
    # 提示名称格式化结果
    if skill_name != raw_skill_name:
        print(f"提示：技能名称已从 '{raw_skill_name}' 格式化为 '{skill_name}'")

    # 解析并校验资源参数
    resources = parse_resources(args.resources)
    # 校验：--examples 必须配合 --resources 使用
    if args.examples and not resources:
        print("[错误] --examples 参数必须配合 --resources 使用")
        sys.exit(1)

    # 打印初始化配置信息
    path = args.path
    print(f"正在初始化技能：{skill_name}")
    print(f"   存放路径：{path}")
    if resources:
        print(f"   资源目录：{', '.join(resources)}")
        if args.examples:
            print("   示例文件：已启用")
    else:
        print("   资源目录：无（按需创建）")
    print()

    # 执行技能初始化
    result = init_skill(skill_name, path, resources, args.examples)

    # 根据结果退出程序
    sys.exit(0 if result else 1)


# 程序入口
if __name__ == "__main__":
    main()