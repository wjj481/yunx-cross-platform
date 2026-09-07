# iOS 构建说明

YunX 移动端 GUI 使用 Kivy 跨平台框架开发，可通过 **kivy-ios** 工具链构建 iOS 应用。

> **注意**：iOS 构建必须在 macOS 上进行，且需要安装 Xcode 和 Apple 开发者账号（用于真机部署和发布）。

## 1. 环境准备

### 1.1 系统要求

- macOS 12 (Monterey) 或更高版本
- Xcode 14+（含 Command Line Tools）
- Python 3.10+
- Homebrew

### 1.2 安装依赖

```bash
# 安装 Homebrew（如未安装）
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# 安装系统依赖
brew install python@3.10 autoconf automake libtool pkg-config
brew install --cask xcode

# 接受 Xcode 许可
sudo xcodebuild -license accept
sudo xcode-select --install
```

### 1.3 安装 kivy-ios

```bash
# 创建虚拟环境
python3.10 -m venv ~/kivy-ios-env
source ~/kivy-ios-env/bin/activate

# 安装 kivy-ios
pip install kivy-ios
```

## 2. 构建 Python 依赖

kivy-ios 需要为 iOS 平台（arm64 设备 + x86_64 模拟器）交叉编译所有 Python 依赖。

```bash
# 进入项目目录
cd /path/to/yunx-cross-platform

# 构建核心依赖（这一步耗时较长，约 30-60 分钟）
toolchain build python3 kivy requests cryptography certifi charset-normalizer idna urllib3

# 验证构建结果
toolchain status
```

### 2.1 依赖说明

| 包名 | 用途 |
|------|------|
| python3 | Python 3.10 运行时 |
| kivy | GUI 框架 |
| requests | HTTP 请求（核心引擎） |
| cryptography | AES-GCM 加密（ConfigManager） |
| certifi | SSL 证书 |
| charset-normalizer | 字符编码 |
| idna | 域名国际化 |
| urllib3 | HTTP 客户端 |

> **注意**：`cryptography` 包含 Rust 扩展，在 iOS 交叉编译时可能需要额外配置。
> 如果构建失败，可尝试使用纯 Python 替代方案或预编译 wheel。

## 3. 创建 Xcode 项目

```bash
# 在项目根目录执行
toolchain create YunX ./

# 生成的 Xcode 项目位于：
# ./YunX-ios/
```

`toolchain create` 会：
1. 创建 `YunX-ios/` 目录
2. 生成 Xcode 项目文件（`YunX.xcodeproj`）
3. 配置 Python 运行时和依赖
4. 设置入口为 `main.py`

### 3.1 项目结构

```
YunX-ios/
├── YunX.xcodeproj/     # Xcode 项目
├── YunX/
│   ├── main.m          # 应用入口
│   └── ...
└── YourApp/            # Python 源码（符号链接到项目根目录）
```

## 4. 配置 Xcode 项目

### 4.1 打开项目

```bash
open YunX-ios/YunX.xcodeproj
```

### 4.2 基本配置

在 Xcode 中进行以下设置：

1. **Bundle Identifier**: `com.yunx.app`
2. **Version**: `0.1.0`
3. **Build**: `1`
4. **Deployment Target**: iOS 13.0（最低支持）
5. **Supported Destinations**: iPhone, iPad
6. **Device Orientation**: 勾选 Portrait、Landscape Left、Landscape Right（支持横竖屏）

### 4.3 Info.plist 配置

在 `Info.plist` 中添加：

```xml
<!-- 网络访问 -->
<key>NSAppTransportSecurity</key>
<dict>
    <key>NSAllowsArbitraryLoads</key>
    <true/>
</dict>

<!-- 文件分享（允许在"文件"App 中查看下载内容） -->
<key>UIFileSharingEnabled</key>
<true/>
<key>LSSupportsOpeningDocumentsInPlace</key>
<true/>

<!-- 状态栏样式 -->
<key>UIViewControllerBasedStatusBarAppearance</key>
<false/>
```

### 4.4 应用图标

将 `mobile_gui/assets/icon.png` 导入 Xcode 的 `Assets.xcassets/AppIcon.appiconset/`，
并按以下尺寸生成各规格图标：

| 规格 | 尺寸 | 用途 |
|------|------|------|
| 20pt | 60x60 (@3x) | iPhone 通知中心 |
| 29pt | 87x87 (@3x) | iPhone Spotlight/设置 |
| 40pt | 120x120 (@3x) | iPhone Spotlight |
| 60pt | 180x180 (@3x) | iPhone 主屏幕 |
| 76pt | 152x152 (@2x) | iPad 主屏幕 |
| 83.5pt | 167x167 (@2x) | iPad Pro 主屏幕 |
| 1024pt | 1024x1024 | App Store |

可使用以下命令批量生成：

```bash
# 使用 ImageMagick
sips -Z 180 icon.png --out icon-60@3x.png
sips -Z 120 icon.png --out icon-40@3x.png
# ... 以此类推
```

## 5. 代码适配要点

### 5.1 路径适配

代码中已通过 `platform` 模块检测 iOS：

```python
# core_adapter.py 中的 default_download_dir()
if system == "Darwin" and _is_ios():
    return os.path.expanduser("~/Documents/YunX")
```

iOS 应用沙盒目录：
- `~/Documents/` — 用户文档目录（可通过 iTunes 文件共享访问）
- `~/Library/Caches/` — 缓存目录
- `~/tmp/` — 临时目录

### 5.2 不使用 Android 专属 API

代码中所有 Android 专属调用均通过 `kivy.utils.platform` 检测：

```python
from kivy.utils import platform as kivy_platform
if kivy_platform == "android":
    from android.permissions import request_permissions
    ...
```

iOS 上不会执行 Android 权限请求代码。

### 5.3 中文字体

iOS 系统自带 `PingFang.ttc`（苹方字体），代码中已自动检测注册：

```python
"/System/Library/Fonts/PingFang.ttc"
```

无需额外打包中文字体。

## 6. 构建与运行

### 6.1 模拟器运行

```bash
# 在 Xcode 中选择模拟器目标（如 iPhone 15）
# 点击 Run（⌘R）
```

或使用命令行：

```bash
xcodebuild -project YunX-ios/YunX.xcodeproj \
    -scheme YunX \
    -destination 'platform=iOS Simulator,name=iPhone 15' \
    build
```

### 6.2 真机部署

1. 连接 iPhone 到 Mac
2. 在 Xcode 中选择设备
3. 配置签名（Apple Developer Account）
4. 点击 Run
5. 在 iPhone 设置 → 通用 → VPN与设备管理 中信任开发者证书

### 6.3 发布到 App Store

```bash
# Archive 构建
xcodebuild -project YunX-ios/YunX.xcodeproj \
    -scheme YunX \
    -configuration Release \
    archive \
    -archivePath ./YunX.xcarchive

# 导出 IPA
xcodebuild -exportArchive \
    -archivePath ./YunX.xcarchive \
    -exportPath ./export \
    -exportOptionsPlist exportOptions.plist

# 使用 Transporter App 或 altool 上传到 App Store Connect
```

## 7. 常见问题

### Q: cryptography 在 iOS 上构建失败

A: cryptography 3.5+ 使用 Rust 编写扩展。kivy-ios 可能不支持 Rust 交叉编译。
解决方案：
- 使用 `cryptography==3.4.8`（最后一个纯 C 扩展版本）
- 或在 `core/config.py` 中替换为纯 Python AES 实现（如 `pycryptodome`）

### Q: 启动后白屏

A: 检查 Xcode 控制台日志，通常是 Python 导入错误。
确认所有依赖都已通过 `toolchain build` 构建。

### Q: 中文显示为方框

A: iOS 上应自动使用 PingFang 字体。如仍有问题，可手动注册：
```python
from kivy.core.text import LabelBase
LabelBase.register(name="Roboto", fn_regular="/System/Library/Fonts/PingFang.ttc")
```

### Q: 下载的文件在哪里

A: iOS 沙盒中 `~/Documents/YunX/`。在 Info.plist 中启用 `UIFileSharingEnabled` 后，
可通过 Mac Finder（macOS Catalina+）或 iTunes 访问。

## 8. 参考链接

- [kivy-ios GitHub](https://github.com/kivy/kivy-ios)
- [Kivy iOS 官方文档](https://kivy.org/doc/stable/guide/packaging-ios.html)
- [Apple Developer Documentation](https://developer.apple.com/documentation/)
