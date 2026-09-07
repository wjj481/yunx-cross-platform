"""
桌面端 GUI 共享工具与常量。

包含网盘显示名称、颜色映射、字节/速度格式化等通用函数。
"""

from __future__ import annotations

# 网盘标识 → 中文显示名
DRIVE_NAMES: dict[str, str] = {
    "quark": "夸克网盘",
    "pan123": "123云盘",
    "xunlei": "迅雷云盘",
    "baidu": "百度网盘",
    "uc": "UC网盘",
    "caiyun": "和彩云",
}

# 网盘标识 → 标签颜色（十六进制）
DRIVE_COLORS: dict[str, str] = {
    "quark": "#1E88E5",    # 蓝色
    "pan123": "#43A047",   # 绿色
    "xunlei": "#FB8C00",   # 橙色
    "baidu": "#E53935",    # 红色（风控警告）
    "uc": "#757575",       # 灰色
    "caiyun": "#757575",   # 灰色
}

# 网盘标识 → 是否需要风控警告
DRIVE_RISK_WARNING: dict[str, bool] = {
    "baidu": True,
}

# 支持的网盘列表（用于账号管理下拉框等）
SUPPORTED_DRIVES: list[str] = list(DRIVE_NAMES.keys())


def format_size(size_bytes: int) -> str:
    """将字节数格式化为人类可读的文件大小字符串。

    Args:
        size_bytes: 文件大小（字节）。

    Returns:
        格式化后的字符串，如 ``"1.23 GB"``、``"456 MB"``。
    """
    if size_bytes <= 0:
        return "0 B"
    units = ["B", "KB", "MB", "GB", "TB", "PB"]
    idx = 0
    size = float(size_bytes)
    while size >= 1024.0 and idx < len(units) - 1:
        size /= 1024.0
        idx += 1
    if idx == 0:
        return f"{int(size)} {units[idx]}"
    return f"{size:.2f} {units[idx]}"


def format_speed(speed_bytes_per_sec: float) -> str:
    """将下载速度格式化为人类可读字符串。

    Args:
        speed_bytes_per_sec: 速度（字节/秒）。

    Returns:
        格式化后的字符串，如 ``"5.67 MB/s"``。
    """
    if speed_bytes_per_sec <= 0:
        return "0 B/s"
    return f"{format_size(int(speed_bytes_per_sec))}/s"


def get_drive_display(drive: str) -> str:
    """获取网盘的中文显示名。

    Args:
        drive: 网盘标识。

    Returns:
        中文名称；未知网盘返回原始标识。
    """
    return DRIVE_NAMES.get(drive, drive)


def get_drive_color(drive: str) -> str:
    """获取网盘对应的标签颜色。

    Args:
        drive: 网盘标识。

    Returns:
        十六进制颜色字符串；未知网盘返回灰色。
    """
    return DRIVE_COLORS.get(drive, "#757575")


def needs_risk_warning(drive: str) -> bool:
    """判断该网盘解析前是否需要弹出风控警告。

    Args:
        drive: 网盘标识。

    Returns:
        ``True`` 表示需要警告。
    """
    return DRIVE_RISK_WARNING.get(drive, False)
