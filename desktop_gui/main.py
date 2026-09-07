"""
YunX 桌面端 GUI 程序入口。

使用方式::

    python -m desktop_gui.main

或::

    python desktop_gui/main.py
"""

from __future__ import annotations

import sys


def main() -> None:
    """启动 YunX 桌面端应用。"""
    # 确保项目根目录在 sys.path 中（当以脚本方式运行时）
    import os

    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

    try:
        from desktop_gui.app import YunXApp
    except ImportError as exc:
        print(f"无法导入桌面端应用：{exc}", file=sys.stderr)
        print("请确保在项目根目录下运行：python -m desktop_gui.main", file=sys.stderr)
        sys.exit(1)

    app = YunXApp()
    app.mainloop()


if __name__ == "__main__":
    main()
