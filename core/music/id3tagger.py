"""
ID3 标签嵌入工具。

支持将歌曲元数据（歌名/歌手/专辑/封面）写入音频文件：
- **MP3** — ID3v2.3 标签（TIT2/TPE1/TALB/APIC 帧）
- **FLAC** — Vorbis Comment + PICTURE 元数据块

依赖策略：
- 优先使用 ``mutagen`` 库（功能完整，支持多种格式）
- 当 ``mutagen`` 不可用时，降级为纯 Python 实现的基础 ID3v2.3 写入
  （仅支持 MP3 格式的 TIT2/TPE1/TALB/APIC 帧）

纯 Python 降级实现说明：
- ID3v2.3 header：``ID3`` + 版本(03 00) + 标志(00) + 大小(4字节 synchsafe)
- 文本帧：FrameID(4) + 大小(4) + 标志(2) + 编码(1) + 文本
- APIC 帧：FrameID(4) + 大小(4) + 标志(2) + 编码(1) + MIME类型 + 图片类型(1) + 描述 + 图片数据
"""

from __future__ import annotations

import struct
from pathlib import Path
from typing import Any

from .base import SongInfo

# 尝试导入 mutagen
try:
    from mutagen.id3 import ID3, TIT2, TPE1, TALB, APIC, ID3NoHeaderError
    from mutagen.flac import FLAC, Picture
    from mutagen.mp3 import MP3

    _MUTAGEN_AVAILABLE = True
except ImportError:
    _MUTAGEN_AVAILABLE = False


# ---------- 公共接口 ----------

def embed_id3_tags(
    file_path: str | Path,
    song_info: SongInfo,
    cover_image_bytes: bytes | None = None,
) -> bool:
    """将歌曲元数据嵌入音频文件。

    Args:
        file_path: 音频文件路径（MP3 或 FLAC）。
        song_info: 歌曲信息（包含 title/artist/album）。
        cover_image_bytes: 封面图片二进制数据（JPEG/PNG），为 ``None`` 时不嵌入封面。

    Returns:
        嵌入成功返回 ``True``，失败返回 ``False``。

    Example::

        song = SongInfo(song_id="123", title="晴天", artist="周杰伦", album="叶惠美")
        embed_id3_tags("/path/to/song.mp3", song, cover_bytes)
    """
    file_path = Path(file_path)
    if not file_path.exists():
        return False

    ext = file_path.suffix.lower().lstrip(".")

    if _MUTAGEN_AVAILABLE:
        return _embed_with_mutagen(file_path, ext, song_info, cover_image_bytes)
    else:
        return _embed_pure_python(file_path, ext, song_info, cover_image_bytes)


def is_mutagen_available() -> bool:
    """检查 mutagen 库是否可用。

    Returns:
        可用时返回 ``True``。
    """
    return _MUTAGEN_AVAILABLE


# ---------- mutagen 实现 ----------

def _embed_with_mutagen(
    file_path: Path,
    ext: str,
    song_info: SongInfo,
    cover_image_bytes: bytes | None,
) -> bool:
    """使用 mutagen 库嵌入标签。"""
    try:
        if ext == "mp3":
            return _embed_mp3_mutagen(file_path, song_info, cover_image_bytes)
        elif ext == "flac":
            return _embed_flac_mutagen(file_path, song_info, cover_image_bytes)
        else:
            return False
    except Exception:
        return False


def _embed_mp3_mutagen(
    file_path: Path,
    song_info: SongInfo,
    cover_image_bytes: bytes | None,
) -> bool:
    """使用 mutagen 嵌入 MP3 ID3 标签。"""
    try:
        audio = MP3(file_path)
    except Exception:
        return False

    # 获取或创建 ID3 标签
    if audio.tags is None:
        audio.add_tags()
    tags = audio.tags

    # 歌名
    if song_info.title:
        tags["TIT2"] = TIT2(encoding=3, text=song_info.title)
    # 歌手
    if song_info.artist:
        tags["TPE1"] = TPE1(encoding=3, text=song_info.artist)
    # 专辑
    if song_info.album:
        tags["TALB"] = TALB(encoding=3, text=song_info.album)

    # 封面
    if cover_image_bytes:
        mime = _detect_mime(cover_image_bytes)
        # 移除已有封面
        tags.delall("APIC")
        tags["APIC"] = APIC(
            encoding=3,
            mime=mime,
            type=3,  # 封面（front cover）
            desc="Cover",
            data=cover_image_bytes,
        )

    try:
        tags.save(file_path, v2_version=3)
        return True
    except Exception:
        return False


def _embed_flac_mutagen(
    file_path: Path,
    song_info: SongInfo,
    cover_image_bytes: bytes | None,
) -> bool:
    """使用 mutagen 嵌入 FLAC Vorbis Comment 标签。"""
    try:
        audio = FLAC(file_path)
    except Exception:
        return False

    # 清除并设置文本标签
    if song_info.title:
        audio["title"] = song_info.title
    if song_info.artist:
        audio["artist"] = song_info.artist
    if song_info.album:
        audio["album"] = song_info.album

    # 封面
    if cover_image_bytes:
        # 移除已有封面
        audio.clear_pictures()
        pic = Picture()
        pic.data = cover_image_bytes
        pic.type = 3  # front cover
        pic.mime = _detect_mime(cover_image_bytes)
        pic.desc = "Cover"
        audio.add_picture(pic)

    try:
        audio.save()
        return True
    except Exception:
        return False


# ---------- 纯 Python 降级实现（仅 MP3 ID3v2.3） ----------

def _embed_pure_python(
    file_path: Path,
    ext: str,
    song_info: SongInfo,
    cover_image_bytes: bytes | None,
) -> bool:
    """纯 Python 实现 ID3v2.3 标签写入（仅支持 MP3）。

    FLAC 格式在无 mutagen 时不支持标签嵌入。
    """
    if ext != "mp3":
        return False

    try:
        # 读取原始文件内容
        original_data = file_path.read_bytes()

        # 移除已有的 ID3v2 标签（如果存在）
        audio_data = _strip_id3v2(original_data)

        # 构建新的 ID3v2.3 标签
        id3_tag = _build_id3v23_tag(song_info, cover_image_bytes)

        # 写入：ID3 标签 + 原始音频数据
        file_path.write_bytes(id3_tag + audio_data)
        return True
    except Exception:
        return False


def _strip_id3v2(data: bytes) -> bytes:
    """移除 MP3 文件开头的 ID3v2 标签。

    Args:
        data: 原始文件二进制数据。

    Returns:
        去除 ID3v2 标签后的音频数据。
    """
    if len(data) < 10 or data[:3] != b"ID3":
        return data

    # 读取 ID3v2 大小（4 字节 synchsafe integer）
    size_bytes = data[6:10]
    tag_size = _synchsafe_to_int(size_bytes)
    total_size = 10 + tag_size

    # 检查是否有 footer（ID3v2.4 支持）
    if data[5] & 0x10:  # footer flag
        total_size += 10

    if total_size <= len(data):
        return data[total_size:]
    return data


def _build_id3v23_tag(
    song_info: SongInfo,
    cover_image_bytes: bytes | None,
) -> bytes:
    """构建 ID3v2.3 标签二进制数据。

    Args:
        song_info: 歌曲信息。
        cover_image_bytes: 封面图片数据。

    Returns:
        完整的 ID3v2.3 标签（含 header）。
    """
    frames = b""

    # TIT2 — 歌名
    if song_info.title:
        frames += _build_text_frame("TIT2", song_info.title)

    # TPE1 — 歌手
    if song_info.artist:
        frames += _build_text_frame("TPE1", song_info.artist)

    # TALB — 专辑
    if song_info.album:
        frames += _build_text_frame("TALB", song_info.album)

    # APIC — 封面
    if cover_image_bytes:
        frames += _build_apic_frame(cover_image_bytes)

    # 构建 ID3v2.3 header
    # "ID3" + version(03 00) + flags(00) + size(4 bytes synchsafe)
    tag_size = len(frames)
    size_bytes = _int_to_synchsafe(tag_size)
    header = b"ID3" + bytes([0x03, 0x00, 0x00]) + size_bytes

    return header + frames


def _build_text_frame(frame_id: str, text: str) -> bytes:
    """构建 ID3v2.3 文本帧。

    Args:
        frame_id: 帧标识（如 ``"TIT2"``）。
        text: 文本内容。

    Returns:
        帧二进制数据。
    """
    # 使用 UTF-16 编码（encoding byte = 0x01），带 BOM
    encoding = b"\x01"
    text_bytes = text.encode("utf-16")  # 包含 BOM

    frame_data = encoding + text_bytes
    # 帧大小（不含 10 字节帧头）
    size = struct.pack(">I", len(frame_data))
    # 帧标志（2 字节，均为 0）
    flags = b"\x00\x00"

    return frame_id.encode("ascii") + size + flags + frame_data


def _build_apic_frame(image_data: bytes) -> bytes:
    """构建 ID3v2.3 APIC（附加图片）帧。

    Args:
        image_data: 图片二进制数据。

    Returns:
        APIC 帧二进制数据。
    """
    encoding = b"\x00"  # ISO-8859-1（MIME 和描述用）
    mime = _detect_mime(image_data).encode("ascii") + b"\x00"
    picture_type = b"\x03"  # 3 = front cover
    description = b"Cover\x00"  # 描述 + 终止符

    frame_data = encoding + mime + picture_type + description + image_data
    size = struct.pack(">I", len(frame_data))
    flags = b"\x00\x00"

    return b"APIC" + size + flags + frame_data


# ---------- 工具函数 ----------

def _detect_mime(data: bytes) -> str:
    """根据文件头检测图片 MIME 类型。

    Args:
        data: 图片二进制数据。

    Returns:
        MIME 类型字符串（``"image/jpeg"`` / ``"image/png"`` / ``"image/gif"``）。
    """
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    elif data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    elif data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    else:
        return "image/jpeg"  # 默认


def _synchsafe_to_int(data: bytes) -> int:
    """将 synchsafe 整数（4 字节）转换为普通整数。

    每个字节仅使用低 7 位，最高位为 0。

    Args:
        data: 4 字节 synchsafe 数据。

    Returns:
        解析后的整数。
    """
    if len(data) != 4:
        return 0
    return (
        (data[0] & 0x7F) << 21
        | (data[1] & 0x7F) << 14
        | (data[2] & 0x7F) << 7
        | (data[3] & 0x7F)
    )


def _int_to_synchsafe(value: int) -> bytes:
    """将普通整数转换为 4 字节 synchsafe 整数。

    Args:
        value: 待转换的整数（最大 268435455）。

    Returns:
        4 字节 synchsafe 数据。
    """
    value = value & 0x0FFFFFFF  # 限制为 28 位
    return bytes(
        [
            (value >> 21) & 0x7F,
            (value >> 14) & 0x7F,
            (value >> 7) & 0x7F,
            value & 0x7F,
        ]
    )
