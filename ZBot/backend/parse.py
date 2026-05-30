"""文件类型检测模块

通过文件头魔术数字(magic bytes)检测 MIME 类型。
采用 Apache Tika / WHATWG MIME Sniffing 的多层检测策略:
1. 按签名长度降序匹配，避免短签名误命中
2. 支持偏移量检测（如 MP4 的 ftyp 在 offset 4）
3. 特殊格式二次校验（如 RIFF 需区分 WebP/WAV/AVI）
4. ZIP-based 格式细分（docx/xlsx/pptx/apk）
5. 文本启发式兜底
6. 无法识别时返回 application/octet-stream
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# 签名表: (magic_bytes, offset, mime_type)
# 按签名长度降序排列 — 长签名优先匹配，避免短签名误命中
# ---------------------------------------------------------------------------
_SIGNATURES: list[tuple[bytes, int, str]] = [
    # ===== 图片 =====
    (b'\x89PNG\r\n\x1a\n', 0, 'image/png'),
    (b'\xff\xd8\xff\xe0', 0, 'image/jpeg'),          # JFIF
    (b'\xff\xd8\xff\xe1', 0, 'image/jpeg'),          # Exif
    (b'\xff\xd8\xff\xee', 0, 'image/jpeg'),          # Adobe
    (b'\xff\xd8\xff', 0, 'image/jpeg'),              # JPEG 通用兜底
    (b'GIF89a', 0, 'image/gif'),
    (b'GIF87a', 0, 'image/gif'),
    (b'RIFF', 0, 'image/webp'),                      # 需二次校验 offset 8
    (b'\x00\x00\x01\x00', 0, 'image/x-icon'),
    (b'\x00\x00\x02\x00', 0, 'image/x-icon'),       # CUR
    (b'BM', 0, 'image/bmp'),
    (b'II\x2a\x00', 0, 'image/tiff'),                # little-endian
    (b'MM\x00\x2a', 0, 'image/tiff'),                # big-endian

    # ===== 文档 (ZIP-based, 需二次校验) =====
    (b'PK\x03\x04', 0, 'application/zip'),

    # ===== PDF =====
    (b'%PDF', 0, 'application/pdf'),

    # ===== Office 旧格式 (OLE2) =====
    (b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1', 0, 'application/msword'),

    # ===== 视频 / 音频 =====
    # EBML header: Matroska(.mkv) / WebM video / WebM audio 共享同一魔数,
    # 仅凭 magic bytes 无法区分, 需解析 DocType 元素. 统一按 video/webm 处理.
    (b'\x1a\x45\xdf\xa3', 0, 'video/webm'),
    (b'ftyp', 4, 'video/mp4'),                       # MP4 偏移 4 字节
    (b'ID3', 0, 'audio/mpeg'),                       # MP3 with ID3 tag
    (b'\xff\xfb', 0, 'audio/mpeg'),                  # MP3 raw frame
    (b'\xff\xf3', 0, 'audio/mpeg'),                  # MP3 MPEG2
    (b'\xff\xf2', 0, 'audio/mpeg'),                  # MP3 MPEG2.5
    (b'OggS', 0, 'audio/ogg'),
    (b'fLaC', 0, 'audio/flac'),

    # ===== 压缩 =====
    (b'\x1f\x8b', 0, 'application/gzip'),
    (b'BZh', 0, 'application/x-bzip2'),
    (b'\xfd7zXZ\x00', 0, 'application/x-xz'),

    # ===== 可执行 =====
    (b'\x7fELF', 0, 'application/x-elf'),
    (b'MZ', 0, 'application/x-msdos-executable'),

    # ===== 字体 =====
    (b'true', 4, 'font/ttf'),
    (b'wOFF', 0, 'font/woff'),
    (b'wOF2', 0, 'font/woff2'),
    (b'OTTO', 0, 'font/otf'),
]


# ---------------------------------------------------------------------------
# RIFF 容器格式二次校验
# RIFF 是一个通用容器, WebP / WAV / AVI 都用它
# offset 8 处的 4 字节标识决定具体子类型
# ---------------------------------------------------------------------------
_RIFF_SUBTYPE_MAP: dict[bytes, str] = {
    b'WEBP': 'image/webp',
    b'WAV ': 'audio/wav',
    b'AVI ': 'video/x-msvideo',
}


def _verify_riff_subtype(data: bytes) -> str:
    """校验 RIFF 容器的具体子类型"""
    if len(data) >= 12:
        fourcc = data[8:12]
        return _RIFF_SUBTYPE_MAP.get(fourcc, 'application/octet-stream')
    return 'application/octet-stream'


# ---------------------------------------------------------------------------
# ZIP-based 格式细分
# docx / xlsx / pptx / apk / jar / epub 都是 ZIP 包,
# 需要读取内部特定文件来区分
# ---------------------------------------------------------------------------
_ZIP_SUBTYPE_MAP: dict[str, str] = {
    'word/': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    'xl/': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    'ppt/': 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
    'META-INF/': 'application/java-archive',          # JAR/APK
}


def _sniff_zip_subtype(data: bytes) -> str:
    """通过 ZIP 内部结构判断具体格式

    在 ZIP 的 central directory 中搜索特征路径前缀。
    """
    text = data[:8192]  # 只扫描前 8KB 足够找到目录条目

    # APK 特征: AndroidManifest.xml
    if b'AndroidManifest.xml' in text:
        return 'application/vnd.android.package-archive'

    # EPUB 特征: mimetype 文件
    if b'application/epub+zip' in text:
        return 'application/epub+zip'

    # Office 格式: 检查是否包含 word/ xl/ ppt/ 目录
    for prefix, mime in _ZIP_SUBTYPE_MAP.items():
        if prefix.encode() in text:
            return mime

    # JAR 特征: .class 文件
    if b'.class' in text:
        return 'application/java-archive'

    return 'application/zip'


# ---------------------------------------------------------------------------
# 文本类型启发式判断与子类型嗅探
# ---------------------------------------------------------------------------
def _is_text_heuristic(data: bytes) -> bool:
    """启发式判断是否为纯文本

    策略:
    1. 有 null 字节 → 大概率是二进制
    2. 可打印 ASCII + 常见控制符占比 > 85% → 文本
    """
    sample = data[:1024]
    if not sample:
        return False
    if b'\x00' in sample:
        return False
    printable = sum(
        1 for b in sample
        if 0x20 <= b <= 0x7e or b in (0x09, 0x0a, 0x0d)
    )
    return printable / len(sample) > 0.85


def _sniff_text_subtype(data: bytes) -> str:
    """对文本类型做子类型嗅探 (WHATWG MIME Sniffing 简化版)"""
    head = data[:1024].lstrip()

    # HTML
    if head.startswith(b'<'):
        lower = head[:64].lower()
        if b'<html' in lower or b'<!doctype' in lower:
            return 'text/html'
        if head.startswith(b'<?xml'):
            return 'text/xml'
        return 'text/html'

    # JSON
    if head.startswith(b'{') or head.startswith(b'['):
        return 'application/json'

    # JavaScript
    if head.startswith(b'//') or head.startswith(b'/*'):
        return 'application/javascript'

    # CSS
    if head.startswith(b'/*') and b'*/' in head[:256]:
        return 'text/css'

    # Markdown (常见特征: 以 # 或 --- 开头)
    if head.startswith(b'#') or head.startswith(b'---'):
        return 'text/markdown'

    return 'text/plain'


# ---------------------------------------------------------------------------
# 主函数
# ---------------------------------------------------------------------------
def detect_by_magic(data: bytes) -> str:
    """通过文件头魔术数字检测文件类型

    Args:
        data: 文件的原始字节内容（至少读取前 8KB）

    Returns:
        MIME type 字符串, 无法识别时返回 application/octet-stream
    """
    if not data:
        return 'application/octet-stream'

    # 第 1 层: 签名匹配 (按长度降序, 长签名优先)
    for magic_bytes, offset, mime in _SIGNATURES:
        end = offset + len(magic_bytes)
        if len(data) >= end and data[offset:end] == magic_bytes:
            # RIFF 需要二次校验子类型
            if mime == 'image/webp' and magic_bytes == b'RIFF':
                return _verify_riff_subtype(data)
            # ZIP 需要细分 docx/xlsx/pptx/apk
            if mime == 'application/zip':
                return _sniff_zip_subtype(data)
            return mime

    # 第 2 层: 文本启发式兜底
    if _is_text_heuristic(data):
        return _sniff_text_subtype(data)

    # 第 3 层: 无法识别
    return 'application/octet-stream'
