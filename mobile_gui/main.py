"""
YunX 移动端 GUI 入口。

用法::

    python -m mobile_gui.main

在无显示环境（如 CI / 服务器）下，可设置环境变量
``KIVY_WINDOW=sdl2`` 或 ``DISPLAY`` 以验证导入和初始化。
若完全无显示，可使用 ``KIVY_NO_ARGS=1`` 配合 mock 窗口。
"""

from __future__ import annotations

import os
import sys


def main() -> None:
    """启动 YunX 移动端应用。"""
    # 确保项目根目录在 sys.path 中，以便导入 core 包
    project_root = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..")
    )
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

    # 环境变量配置（桌面调试用）
    os.environ.setdefault("KIVY_NO_ARGS", "1")

    from mobile_gui.app import YunXApp

    app = YunXApp()
    app.run()


if __name__ == "__main__":
    main()
