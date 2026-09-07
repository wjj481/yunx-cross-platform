# YunX 跨平台网盘解析 + 高速下载工具

[![License: AGPL v3](https://img.shields.io/badge/License-AGPL%20v3-blue.svg)](https://www.gnu.org/licenses/agpl-3.0)

对标云析 (YunX) 的全平台网盘解析 + 高速下载工具。核心引擎为纯 Python 模块，与 GUI 完全分离，可供桌面端（tkinter）和移动端（Kivy）共同调用。

> 本项目参考 [云析 (YunX)](https://github.com/CYQawa/YunX) 的 Kotlin 实现，用 Python 重写核心解析与下载逻辑。

## 支持网盘列表

| 网盘 | 状态 | 说明 |
|------|------|------|
| 夸克网盘 | ✅ 完整 | 需登录 Cookie（`__pus` / `__puus`） |
| 123 云盘 | ✅ 完整 | 需登录 JWT Token（`authorToken`） |
| 迅雷云盘 | ✅ 完整 | 需 `access_token` + `device_id` |
| 百度网盘 | ⚠️ 实验性 | 有风控风险，需用户确认 |
| UC 网盘 | ⚠️ 实验性 | 框架已搭建，待实现 |
| 和彩云（139） | ⚠️ 实验性 | 框架已搭建，待实现 |

## 项目结构

```
yunx-cross-platform/
├── core/                    # 核心引擎（纯Python，无GUI依赖）
│   ├── parsers/             # 各网盘解析器
│   │   ├── base.py          # 解析器基类 + 工厂函数
│   │   ├── quark.py         # 夸克网盘
│   │   ├── pan123.py        # 123云盘
│   │   ├── xunlei.py        # 迅雷云盘
│   │   ├── baidu.py         # 百度网盘（实验性）
│   │   ├── uc.py            # UC网盘（实验性）
│   │   └── caiyun.py        # 和彩云（实验性）
│   ├── downloader/          # 下载引擎
│   │   ├── engine.py        # Range分片并发下载+断点续传
│   │   └── progress.py      # 进度追踪
│   ├── config.py            # 配置管理（AES-GCM加密）
│   ├── clipboard.py         # 剪贴板识别辅助
│   └── exceptions.py        # 统一异常定义
├── desktop_gui/             # 桌面端GUI（tkinter，待填充）
├── mobile_gui/              # 移动端GUI（Kivy，待填充）
├── build/                   # 打包脚本（待填充）
├── docs/                    # 文档
├── tests/                   # 单元测试
├── requirements.txt         # 全量依赖
├── requirements-core.txt    # 仅核心引擎依赖
├── setup.py
├── LICENSE                  # AGPL-3.0
└── README.md
```

## 核心引擎 API 文档

### 解析分享链接

```python
from core.parsers import get_parser, ShareInfo
from core.config import ConfigManager

# 加载加密配置
cfg = ConfigManager("your_master_password")
credential = cfg.get_credential("quark")

# 根据 URL 自动匹配解析器
parser = get_parser("https://pan.quark.cn/s/abc123", credential=credential)

# 解析分享链接（自动从 URL 提取提取码）
info: ShareInfo = parser.parse_share_url("https://pan.quark.cn/s/abc123")

print(f"文件名: {info.file_name}")
print(f"大小: {info.file_size} 字节")
print(f"直链: {info.direct_url}")
```

### 下载文件

```python
from core.downloader import DownloadEngine

engine = DownloadEngine(concurrency=8, chunk_size=4 * 1024 * 1024)

def on_progress(progress):
    print(f"\r{progress.percent:.1f}%  {progress.speed/1024:.0f} KB/s", end="")

output = engine.download(
    url=info.direct_url,
    output_path="/tmp/downloads/file.zip",
    progress_callback=on_progress,
    headers={"Referer": "https://pan.quark.cn/"},
)

# 暂停 / 恢复 / 取消
engine.pause()
engine.resume()
engine.cancel()
```

### 剪贴板识别

```python
from core.clipboard import detect_share_url

results = detect_share_url("分享链接：https://pan.quark.cn/s/abc 提取码: 1234")
for r in results:
    print(f"{r.drive}: {r.url} (提取码: {r.extract_code})")
```

### 加密配置管理

```python
from core.config import ConfigManager

cfg = ConfigManager("master_password")

# 保存凭证（AES-GCM 加密存储到 ~/.yunx/config.enc）
cfg.set_credential("quark", {"cookie": "__pus=...; __puus=..."})
cfg.set_credential("pan123", {"access_token": "eyJ..."})

# 读取凭证
cookie = cfg.get_credential("quark")["cookie"]
```

### 下载引擎特性

- **Range 分片并发下载**：自动检测服务器 Range 支持，分片大小可配置（默认 4MB），并发数上限 32（默认 8）
- **断点续传**：下载状态持久化到 `.yunx_download.json` 元数据文件，中断后自动跳过已完成分片
- **暂停/恢复**：线程安全的暂停/恢复控制
- **进度回调**：实时报告 `downloaded_bytes`、`total_bytes`、`speed`、`percent`
- **文件合并**：所有分片下载完成后按顺序合并为最终文件
- **校验**：可选 MD5/SHA256 校验
- **自动重试**：单分片最多重试 5 次，指数退避

### 异常体系

```python
from core.exceptions import (
    YunXError, ParserError, NetworkError,
    DownloadError, BaiduRiskWarning, AuthenticationError,
)
```

| 异常 | 说明 |
|------|------|
| `YunXError` | 所有异常的基类 |
| `ParserError` | 解析失败（分享失效、提取码错误等） |
| `NetworkError` | 网络请求失败 |
| `DownloadError` | 下载引擎失败 |
| `BaiduRiskWarning` | 百度网盘风控警告 |
| `AuthenticationError` | 认证失败（Cookie/Token 过期） |

## 安装

```bash
# 仅核心引擎
pip install -r requirements-core.txt

# 完整（含 GUI 和打包工具）
pip install -r requirements.txt

# 或作为包安装
pip install -e .
```

## 运行测试

```bash
cd yunx-cross-platform
python -m pytest tests/ -v
```

## 免责声明

1. 本工具仅供学习和研究使用，请勿用于商业用途。
2. 使用本工具下载的内容应遵守相关法律法规和网盘服务条款。
3. 百度网盘等平台对自动化解析有严格的风控策略，使用实验性功能可能导致账号被封禁，使用者需自行承担风险。
4. 本项目不存储任何用户数据，所有凭证均在本地 AES-GCM 加密存储。
5. 本项目基于 AGPL-3.0 协议开源，衍生作品必须同样以 AGPL-3.0 开源。

## License

[GNU Affero General Public License v3.0](LICENSE)
