from PIL import Image, ImageOps
import numpy as np

def display_vector_in_terminal(image_path, width=30):
    """
    专为矢量线条图设计的终端显示方案
    优化点：
    1. 保留矢量图的线条锐利度
    2. 精确处理黑白对比
    3. 小尺寸下保持清晰度
    """
    # 1. 读取并处理矢量图
    img = Image.open(image_path).convert('L')  # 转为灰度图
    img = ImageOps.invert(img)  # 反转：让黑色线条变成白色（终端显示更清晰）
    
    # 2. 智能缩放 - 保持线条锐利
    aspect_ratio = img.height / img.width
    new_height = int(width * aspect_ratio * 0.55)  # 优化比例因子
    img = img.resize((width, new_height), Image.LANCZOS)
    
    # 3. 二值化处理（关键！针对矢量图）
    threshold = 200  # 针对线条图的特殊阈值
    img = img.point(lambda p: 255 if p > threshold else 0)
    
    # 4. 转换为终端字符
    pixels = np.array(img)
    chars = "  .:;I!l1i|\\/-_(){}[]<>+=*?^@&%$#"
    
    # 5. 生成高对比度字符画
    for y in range(pixels.shape[0]):
        line = ""
        for x in range(pixels.shape[1]):
            # 使用高对比度字符
            if pixels[y, x] > 200:
                line += "█"  # 实心方块
            else:
                line += " "  # 空格
        print(line)

# 使用示例 - 精确控制尺寸
display_vector_in_terminal("E:\LLMsApplicationDevelopment\ZBot\logo_for_ZBot.png", width=28)