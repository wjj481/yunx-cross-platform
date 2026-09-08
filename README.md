# YunX 全平台多媒体解析下载 + 云盘上传工具

[![License: AGPL v3](https://img.shields.io/badge/License-AGPL%20v3-blue.svg)](https://www.gnu.org/licenses/agpl-3.0)
[![Version](https://img.shields.io/badge/version-0.3.0-green.svg)](https://github.com/wjj481/yunx-cross-platform/releases)
[![Tests](https://img.shields.io/badge/tests-254%20passed-brightgreen.svg)]()

对标云析 (YunX) 的全平台网盘解析 + 高速下载工具，v0.3.0 新增**视频解析下载**、**音乐解析下载**和**云盘上传**功能。核心引擎为纯 Python 模块，与 GUI 完全分离，可供桌面端（tkinter）和移动端（Kivy）共同调用。

> 本项目参考 [云析 (YunX)](https://github.com/CYQawa/YunX) 的 Kotlin 实现，用 Python 重写核心解析与下载逻辑。

---

## ✨ 功能总览

| 模块 | 功能 | 状态 |
|------|------|------|
| 网盘解析 | 夸克/123/迅雷/百度/UC/和彩云 分享链接解析 + 直链获取 | ✅ |
| 高速下载 | Range分片并发（上限32）+ 断点续传 + 进度显示 | ✅ |
| 视频解析 | B站/抖音/YouTube 等12个平台视频解析下载 | ✅ v0.3.0 |
| 音乐解析 | 网易云/QQ音乐 等4个平台歌曲/歌单解析 + ID3标签 | ✅ v0.3.0 |
| 云盘上传 | 夸克/123/百度/迅雷 分片上传 + 断点续传 + 分享链接 | ✅ v0.3.0 |
| 配置管理 | AES-256-GCM 凭证加密 + 配置导出/导入（.yunxcfg） | ✅ |
| 全平台GUI | 桌面端 tkinter 标签页 + 移动端 Kivy 底部导航 | ✅ |

---

## 📁 支持平台列表

### 网盘解析

| 网盘 | 状态 | 说明 |
|------|------|------|
| 夸克网盘 | ✅ 完整 | 需登录 Cookie（`__pus` / `__puus`） |
| 123 云盘 | ✅ 完整 | 需登录 JWT Token（`authorToken`） |
| 迅雷云盘 | ✅ 完整 | 需 `access_token` + `device_id` |
| 百度网盘 | ⚠️ 实验性 | 有风控风险，需用户确认 |
| UC 网盘 | ⚠️ 实验性 | 框架已搭建 |
| 和彩云（139） | ⚠️ 实验性 | 框架已搭建 |

### 视频解析

| 平台 | 状态 | 说明 |
|------|------|------|
| B站 (bilibili) | ✅ 完整 | BV/AV号、分P、wbi签名、DASH流、登录Cookie获取4K |
| 抖音 (douyin) | ✅ 完整 | 短链重定向、X-Bogus签名、无水印直链 |
| YouTube | ✅ 完整 | 60+ itag映射、渐进式+DASH、yt-dlp可选后端 |
| 快手 | ⚠️ 实验性 | 框架已搭建 |
| 微博视频 | ⚠️ 实验性 | 框架已搭建 |
| 小红书 | ⚠️ 实验性 | 框架已搭建 |
| 西瓜视频 | ⚠️ 实验性 | 框架已搭建 |
| 知乎视频 | ⚠️ 实验性 | 框架已搭建 |
| Twitter/X | ⚠️ 实验性 | 框架已搭建 |
| TikTok | ⚠️ 实验性 | 框架已搭建 |
| Instagram | ⚠️ 实验性 | 框架已搭建 |
| Facebook | ⚠️ 实验性 | 框架已搭建 |

### 音乐解析

| 平台 | 状态 | 说明 |
|------|------|------|
| 网易云音乐 | ✅ 完整 | weapi/eapi加密、单曲/歌单/专辑、登录Cookie获取无损 |
| QQ音乐 | ✅ 完整 | vkey签名、guid生成、songmid/歌单/专辑 |
| 酷狗音乐 | ⚠️ 实验性 | 框架已搭建 |
| 酷我音乐 | ⚠️ 实验性 | 框架已搭建 |

音质：`standard`（MP3 128kbps）/ `higher`（MP3 320kbps）/ `lossless`（FLAC无损）

### 云盘上传

| 网盘 | 状态 | 说明 |
|------|------|------|
| 夸克网盘 | ✅ 完整 | upload_token → OSS分片 → commit，含秒传检测 |
| 123云盘 | ✅ 完整 | CRC32签名、mupload → 分片 → commit |
| 百度网盘 | ✅ 完整 | precreate → superfile2 → create，**强制风控警告** |
| 迅雷网盘 | ✅ 完整 | captcha_sign 10层MD5、uploadInit → 分片 → uploadCommit |

---

## 🏗️ 项目结构

```
yunx-cross-platform/
├── core/                         # 核心引擎（纯Python，无GUI依赖）
│   ├── parsers/                  # 网盘解析器
│   │   ├── base.py               # 解析器基类 + 工厂函数
│   │   ├── quark.py              # 夸克网盘
│   │   ├── pan123.py             # 123云盘
│   │   ├── xunlei.py             # 迅雷云盘
│   │   ├── baidu.py              # 百度网盘（实验性）
│   │   ├── uc.py                 # UC网盘（实验性）
│   │   └── caiyun.py             # 和彩云（实验性）
│   ├── video/                    # 视频解析下载（v0.3.0新增）
│   │   ├── base.py               # 视频解析器基类 + 工厂 + VideoInfo
│   │   ├── bilibili.py           # B站（完整）
│   │   ├── douyin.py             # 抖音（完整）
│   │   ├── youtube.py            # YouTube（完整）
│   │   ├── downloader.py         # VideoDownloader 集成类
│   │   └── ...                   # 其他9个实验性平台
│   ├── music/                    # 音乐解析下载（v0.3.0新增）
│   │   ├── base.py               # 音乐解析器基类 + 工厂 + SongInfo/PlaylistInfo
│   │   ├── netease.py            # 网易云音乐（完整）
│   │   ├── qqmusic.py            # QQ音乐（完整）
│   │   ├── id3tagger.py          # ID3标签嵌入（mutagen + 纯Python降级）
│   │   ├── downloader.py         # MusicDownloader 集成类
│   │   └── ...                   # 酷狗/酷我实验性平台
│   ├── uploader/                 # 云盘上传引擎（v0.3.0新增）
│   │   ├── base.py               # 上传器基类 + 工厂 + UploadTask
│   │   ├── quark_uploader.py     # 夸克网盘上传
│   │   ├── pan123_uploader.py    # 123云盘上传
│   │   ├── baidu_uploader.py     # 百度网盘上传（含风控警告）
│   │   ├── xunlei_uploader.py    # 迅雷网盘上传
│   │   └── engine.py             # 上传引擎（分片并发+断点续传）
│   ├── downloader/               # 下载引擎
│   │   ├── engine.py             # Range分片并发下载+断点续传
│   │   └── progress.py           # 进度追踪
│   ├── config_export.py          # 配置导出/导入（AES-256-GCM，.yunxcfg）
│   ├── config.py                 # 配置管理（AES-GCM加密）
│   ├── clipboard.py              # 剪贴板识别辅助
│   └── exceptions.py             # 统一异常定义
├── desktop_gui/                  # 桌面端GUI（tkinter，Material 3风格）
│   ├── app.py                    # 主应用（ttk.Notebook 四标签页）
│   ├── theme.py                  # Material 3 主题管理器
│   ├── pages/                    # 解析/下载管理/账号管理/设置 四页
│   ├── widgets/                  # 自定义组件
│   ├── dialogs/                  # 对话框（账号/设置/配置导出/上传）
│   └── desktop_gui.spec          # PyInstaller 打包配置
├── mobile_gui/                   # 移动端GUI（Kivy，Material 3风格）
│   ├── app.py                    # 主应用（底部导航栏四Tab）
│   ├── core_adapter.py           # 核心引擎适配器
│   ├── ui/                       # 组件/对话框/四个屏幕
│   └── buildozer.spec            # Android 打包配置
├── build/                        # 打包脚本 + 维护脚本
│   ├── scripts/                  # build_windows.sh / build_linux.sh
│   └── maintenance/              # project_maintenance.py + scheduler
├── docs/                         # 文档（iOS构建说明等）
├── tests/                        # 单元测试（254个测试用例）
├── requirements.txt              # 全量依赖
├── requirements-core.txt         # 仅核心引擎依赖
├── setup.py
├── LICENSE                       # AGPL-3.0
└── README.md
```

---

## 🚀 快速开始

### 安装

```bash
# 仅核心引擎
pip install -r requirements-core.txt

# 完整（含 GUI 和打包工具）
pip install -r requirements.txt

# 或作为包安装
pip install -e .
```

### 运行 GUI

```bash
# 桌面端
python -m desktop_gui.main

# 移动端（开发调试）
python -m mobile_gui.main
```

### 运行测试

```bash
python -m pytest tests/ -v
# 254 passed
```

---

## 📖 核心引擎 API 文档

### 1. 网盘解析 + 下载

```python
from core.parsers import get_parser
from core.downloader import DownloadEngine
from core.config import ConfigManager

# 加载加密配置
cfg = ConfigManager("your_master_password")
credential = cfg.get_credential("quark")

# 根据 URL 自动匹配解析器
parser = get_parser("https://pan.quark.cn/s/abc123", credential=credential)
info = parser.parse_share_url("https://pan.quark.cn/s/abc123")

# 高速下载（Range分片并发+断点续传）
engine = DownloadEngine(concurrency=8, chunk_size=4*1024*1024)
output = engine.download(
    url=info.direct_url,
    output_path="/tmp/downloads/file.zip",
    progress_callback=lambda p: print(f"{p.percent:.1f}% {p.speed/1024:.0f}KB/s"),
    headers={"Referer": "https://pan.quark.cn/"},
)
```

### 2. 视频解析下载（v0.3.0）

```python
from core.video import VideoDownloader

dl = VideoDownloader(concurrency=8)

# 解析视频链接（B站/抖音/YouTube等）
info = dl.parse("https://www.bilibili.com/video/BV1xx411c7mD")
print(f"标题: {info.title}")
print(f"时长: {info.duration}秒")
print(f"清晰度: {[q.quality for q in info.quality_list]}")

# 选择清晰度下载
dl.download(
    info,
    quality="1080p",
    output_dir="./videos",
    progress_callback=lambda p: print(f"{p.percent:.1f}%"),
)
```

### 3. 音乐解析下载（v0.3.0）

```python
from core.music import MusicDownloader

dl = MusicDownloader(output_dir="./music")

# 解析单曲
song = dl.parse_song("https://music.163.com/#/song?id=123456")
print(f"{song.title} - {song.artist} ({song.album})")

# 下载（自动嵌入ID3标签：歌名/歌手/专辑/封面）
path = dl.download_song(url, quality="higher")  # higher=320kbps

# 歌单批量下载
paths = dl.download_playlist(playlist_url, quality="standard")
```

### 4. 云盘上传（v0.3.0）

```python
from core.uploader import get_uploader
from core.config import ConfigManager

cfg = ConfigManager("your_master_password")
credential = cfg.get_credential("quark")

# 获取上传器
uploader = get_uploader("quark", credential)

# 获取远程目录列表
dirs = uploader.get_remote_dirs(parent_dir=None)
for d in dirs:
    print(f"{d.file_id}: {d.file_name}")

# 上传文件（分片并发+断点续传）
result = uploader.upload_file(
    file_path="/tmp/downloads/video.mp4",
    remote_dir="/uploads",
    progress_callback=lambda p: print(f"{p.percent:.1f}% {p.speed/1024:.0f}KB/s"),
)

# 生成分享链接
share = uploader.create_share_link(result.file_id)
print(f"分享链接: {share.share_url}")
```

### 5. 配置导出/导入

```python
from core.config_export import export_config, import_config, is_encrypted, apply_imported_config
from core.config import ConfigManager

cfg = ConfigManager("master_password")

# 加密导出（AES-256-GCM）
export_config(cfg, "backup.yunxcfg", password="my_export_password", include_tasks=True)

# 明文导出
export_config(cfg, "backup_plain.yunxcfg", password=None)

# 导入（自动检测加密）
if is_encrypted("backup.yunxcfg"):
    data = import_config("backup.yunxcfg", password="my_export_password")
else:
    data = import_config("backup.yunxcfg")

# 应用到配置（merge合并 / replace替换）
apply_imported_config(cfg, data, merge=True)
```

---

## ⚙️ 下载/上传引擎特性

### 下载引擎
- **Range 分片并发下载**：自动检测服务器 Range 支持，分片默认4MB（最小64KB），并发上限32（默认8）
- **断点续传**：状态持久化到 `.yunx_download.json`，中断后自动跳过已完成分片
- **暂停/恢复/取消**：线程安全的事件控制
- **进度回调**：实时报告 `downloaded_bytes`、`total_bytes`、`speed`（滑动窗口）、`percent`
- **文件合并**：分片按序拼接，原子写入
- **自动重试**：单分片最多5次，指数退避
- **单线程降级**：服务器不支持Range时自动切换流式下载

### 上传引擎
- **分片并发上传**：默认4MB分片，默认4线程（上限16）
- **断点续传**：元数据持久化到 `.yunx_upload.json`
- **秒传检测**：init阶段检测MD5/SHA1，命中则直接返回
- **暂停/恢复/取消**：`threading.Event` 线程安全控制
- **自动重试**：单分片最多5次，指数退避
- **分享链接**：上传完成后可生成分享链接

---

## 📦 打包发布

### 支持平台

| 平台 | 架构 | 状态 |
|------|------|------|
| Windows | x64 (64位) | ✅ 可执行文件 |
| Windows | x86 (32位) | ✅ 可执行文件（兼容Win7 32位） |
| Linux | x86_64 | ✅ 可执行文件 |
| macOS | x86_64/arm64 | 📝 构建脚本 + GitHub Actions |
| Android | arm64-v8a/armeabi-v7a | 📝 buildozer 配置 |
| iOS | arm64 | 📝 Xcode项目 + 爱思助手签名教程 |

### 本地打包

```bash
# Windows (64位 + 32位，需Wine)
bash build/scripts/build_windows.sh

# Linux
bash build/scripts/build_linux.sh
```

### GitHub Release

最新版本：https://github.com/wjj481/yunx-cross-platform/releases

---

## 🔧 异常体系

```python
from core.exceptions import (
    YunXError, ParserError, NetworkError, DownloadError,
    BaiduRiskWarning, AuthenticationError, UploadError,
    QuotaExceededError, VideoParseError, MusicParseError,
)
```

| 异常 | 说明 |
|------|------|
| `YunXError` | 所有异常的基类 |
| `ParserError` | 解析失败（分享失效、提取码错误等） |
| `NetworkError` | 网络请求失败 |
| `DownloadError` | 下载引擎失败 |
| `UploadError` | 上传失败 |
| `QuotaExceededError` | 网盘空间不足 |
| `BaiduRiskWarning` | 百度网盘风控警告 |
| `AuthenticationError` | 认证失败（Cookie/Token 过期） |
| `VideoParseError` | 视频解析失败 |
| `MusicParseError` | 音乐解析失败 |

---

## ⚠️ 免责声明

1. 本工具仅供个人学习和研究使用，请勿用于商业用途。
2. 使用本工具下载的内容应遵守相关法律法规和各平台服务条款，请尊重版权，下载内容请于24小时内删除。
3. 百度网盘等平台对自动化操作有严格的风控策略，使用相关功能可能导致账号被封禁，使用者需自行承担风险。
4. 视频/音乐解析接口可能随时变化，代码中已做优雅降级和错误提示，实验性平台不保证可用性。
5. 本项目不存储任何用户数据，所有凭证均在本地 AES-256-GCM 加密存储。
6. 本项目基于 AGPL-3.0 协议开源，衍生作品必须同样以 AGPL-3.0 开源。

---

## 📄 License

[GNU Affero General Public License v3.0](LICENSE)
