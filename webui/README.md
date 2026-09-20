# 云析 Web 客户端 (yunx-web-client)
> ⚠️ 本项目全部代码与内容由 AI 生成，仅供学习交流使用，请勿用于商业用途。


纯前端 iOS 网页版视频/音乐解析下载工具，无需电脑/安卓主机，iPhone Safari 直接使用。

## 功能

- 粘贴链接 → 前端解析直链
- m3u8 分片下载合并
- Safari 直接下载到 iPhone「文件」App
- 进度条、多任务队列（1-2 并发）
- PWA：可添加到 iOS 主屏幕
- 中文 UI、移动端适配

## 支持平台

| 平台 | 视频 | 音乐 | 说明 |
|------|------|------|------|
| B站 (bilibili) | ✅ | - | BV号识别、分P、清晰度选择 |
| 抖音 (douyin) | ✅ | - | 短链解析、无水印 |
| YouTube | ✅ | - | ID提取、清晰度选择 |
| 网易云音乐 | - | ✅ | 歌曲解析、音质选择 |
| QQ音乐 | - | ✅ | 歌曲解析、音质选择 |

## 技术栈

- 纯 HTML/CSS/JS（无框架、无构建工具）
- m3u8 解析 + 分片下载合并（原生 Fetch API + Blob）
- PWA: manifest.json + service-worker.js
- CORS 代理可配置（默认 corsproxy.io）

## 已知限制

- 浏览器跨域限制，**不支持自动上传云盘**
- DRM/加密视频不支持，提示"资源受保护"
- 部分平台防盗链可能解析失败
- B站高清晰度和无损音质需登录 Cookie（纯前端无法安全保存）
- 解析接口可能随时变化

## 免责声明

本工具仅供个人学习与技术研究使用，请勿用于商业用途或侵犯他人版权。下载内容请于 24 小时内删除。

## 目录结构

```
webui/
├── index.html          # 主页面
├── css/style.css       # 样式
├── js/
│   ├── crypto.js       # 加密工具（MD5/AES/RSA/wbi签名）
│   ├── parsers.js      # 各平台解析器
│   ├── m3u8.js         # m3u8 下载合并
│   ├── downloader.js   # 下载管理器
│   └── app.js          # 主应用
├── manifest.json       # PWA manifest
├── sw.js               # Service Worker
└── icons/              # PWA 图标
```

## 部署

静态文件部署到 Netlify：

```bash
cd webui
netlify deploy --prod --dir .
```

或通过 GitHub 连接 Netlify 自动部署，base directory 设为 `webui/`。

## 版本

v0.1.0 - 初始版本
