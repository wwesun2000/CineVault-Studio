# CineVault Studio (影库枢机)

[![Release Build](https://github.com/wwesun2000/CineVault-Studio/actions/workflows/release.yml/badge.svg)](https://github.com/wwesun2000/CineVault-Studio/actions/workflows/release.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-3776AB.svg)](https://www.python.org/)
[![Platform: Windows | Web/PWA](https://img.shields.io/badge/Platform-Windows%20%7C%20Web%2FPWA-0078D6.svg)](#)

**CineVault Studio（影库枢机）** 是一款面向本地磁盘、Samba/SMB NAS 与网盘挂载的**三轨本地影视资料库管理系统**（支持欧美成人厂牌、日本 AV 番号、常规院线电影/剧集），采用 **Python 零依赖核心引擎 + 响应式双主题 Web/PWA 界面 + PyInstaller 单文件绿色版**架构，并深度集成 **AI 元数据与标签校对工作流（CLI Markdown / MCP）** 及 **跨平台哈希同步包（`.cvpack`）**。

> **CineVault Studio** is a zero-dependency local/NAS media library manager & cross-platform sync engine featuring O(1) 3-chunk partial BLAKE2b hashing, tri-engine metadata parsing (Western Adult / Japanese JAV / Mainstream Cinema), local poster persistence, first-class VLC integration, and dual-mode AI metadata/tag enrichment (CLI Markdown in-place editing & MCP).

---

## ✨ 核心特性 (Key Features)

### 1. 极速复合哈希与无感移动重定位 (`src/core/hasher.py`)
- 针对 10GB+ 4K 大文件与 SMB/NAS 共享目录，采用 **O(1) 三段 64KB 采样 BLAKE2b-256 复合指纹**（文件大小 + 首部 64KB + 中部 64KB + 尾部 64KB），单文件校验仅需数毫秒。
- 增量刷新时自动缓存 `(path, size, mtime)` 并并发计算新文件哈希；即使文件被移动目录或重命名，也能通过哈希自动重定位，**完整保留你的半星评分、标签、用户备注与播放进度**。

### 2. 三轨启发式多维线索解析 (`src/core/parser.py` + `src/adapters/http_server.py`)
- **多维线索融合**：同时结合「文件名日期」「系列/厂牌目录」「女优专属目录（如 `女优/<演员名>`）」「视频时长 `duration_sec`」与「用户备注 `user_keywords`」，自动修复双词人名拆分、厂牌缩写、年份前缀（`[19]Studio...`）、水印前缀与合集误判。
- **内置 50+ 欧美厂牌与系列必有标签规则**：自动规范化厂牌名称并过滤无效目录名（未知目录自动归入 `🆕 未分类 (待AI)`）；自动为 `Lubed` (`Oil`)、`Tushy` (`Anal`)、`Blacked` (`Interracial`)、`Hogtied` (`Bondage`)、`Anal Oil Latex` (`Anal`+`Oil`+`Latex`) 等系列补齐必有标签。
- **纯 Python 极速视频时长探测**：直接解析 MP4/MOV/M4V `moov/mvhd` 原子头获取准确时长（零子进程开销，支持 FFmpeg 回退），轻松区分单场（Scene）与合集（Compilation）。

### 3. 本地优先的封面持久化与可选 FFmpeg 兜底
- 支持接入 **ThePornDB API Token**（欧美成人）与 **TMDB API Key**（常规电影），在设置界面提供免费申请直达链接。
- **所有在线刮削海报均自动下载并持久化至本地 `.cinevault_covers/` 目录**，完全支持离线浏览与跨端 `.cvpack` 同步包导出。
- 无需强制安装 FFmpeg 即可运行；仅在无本地/在线封面时提供按需 FFmpeg 智能避黑帧截帧（`max(15%, 120s)`）作为最后兜底方案。

### 4. 双模式 AI 元数据补全与标签专项校对 (`AI_KEYWORD_DB.md` / MCP)
- **模式 B（推荐：CLI 就地编辑）**：支持两种导出模式，按 **每批 25 条** 写入根目录 `AI_KEYWORD_DB.md`（附带 `AI_ENRICHMENT_GUIDE.md`）：
  1. **综合补全模式 (`incomplete`)**：导出待补全元数据与未收录新厂牌。
  2. **标签专项校对模式 (`tags_only`)**：导出标签为空或缺失系列标签的记录（含已完成记录），**导入时锁死厂牌/标题/演员/日期，只安全合并非空 `tags`**。
- **内置四条防幻觉铁律**：明确证据匹配顺序、系列必有标签对照表、85+ 库内标准标签词表、“对不上就留空并写 `tag_note`”、厂牌登记红线及 18+ 合规基准；**导入时空 `tags: []` 绝不覆盖库内已有标签**，并支持截断 JSON 容错恢复。
- **标准 MCP Server (`src/adapters/mcp_stdio_server.py`)**：提供 `list_incomplete_media`、`get_keyword_glossary`、`apply_enriched_metadata`、`register_new_studio` 工具。

### 5. 一键前台唤起 VLC 与内置 Range 流媒体播放
- 自动检测本机 **VLC Media Player**（及 PotPlayer / MPV），点击直接前台唤起播放并支持断点续播（`--start-time`）；同时内置 HTTP `206 Partial Content` 视频流播放器，支持局域网手机浏览器与 Android `vlc://` 协议直连。

### 6. 跨平台同步包 (`.cvpack`) 与绿色便携设计
- Windows 端一键导出包含元数据、半星评分、自定义标签与本地封面的 `.cvpack` 同步包，供 Android 端或另一台电脑按文件哈希自动映射路径导入。
- **全绿便携**：数据库 `cinevault_library.db`、配置 `config.json`、本地封面 `.cinevault_covers/` 与 `AI_KEYWORD_DB.md` 均严格保存在程序所在目录，不污染系统目录。
- **隐私模糊快捷键 (`Ctrl + B`)** & **一键仅看常规电影模式**，方便公共场合浏览或演示。

---

## 🖼️ 界面预览 (UI Concepts)

- **曜石影院深色主题 (Obsidian Cinema)**：[theme_dark_obsidian_cinema.jpg](docs/ui_concepts/theme_dark_obsidian_cinema.jpg)
- **暖白画廊浅色主题 (Nordic Gallery)**：[theme_light_nordic_gallery.jpg](docs/ui_concepts/theme_light_nordic_gallery.jpg)

---

## 🚀 快速开始 (Quick Start)

### 方式一：直接下载 Windows 绿色便携版（推荐）
1. 前往本仓库右侧的 **[Releases](https://github.com/wwesun2000/CineVault-Studio/releases)** 页面。
2. 下载最新版本的 `CineVaultStudio_Portable.zip` 并解压到任意文件夹。
3. 双击运行 `CineVaultStudio.exe`，程序将自动启动本地服务并在默认浏览器中打开 `http://127.0.0.1:8765`。
4. 点击右上角 **「⚙ 设置」** 添加本地视频目录或 Samba NAS 路径（如 `\\192.168.1.50\Media`），再点击 **「↻ 刷新并校验哈希」** 即可完成建库。

### 方式二：从源码运行（Python 3.10+ 零依赖）
```bash
git clone https://github.com/wwesun2000/CineVault-Studio.git
cd CineVault-Studio
python scripts/run_dev.py
```

可选启动参数：
```bash
# 指定端口且不自动打开浏览器
python scripts/run_dev.py --host 127.0.0.1 --port 8765 --no-browser

# 运行启动自检（验证 UI 与 REST API）
python scripts/run_dev.py --self-check
```

### 方式三：安装 Android 安卓通用版（支持导入电脑端数据）
1. 前往本仓库右侧的 **[Releases](https://github.com/wwesun2000/CineVault-Studio/releases)** 页面，下载 **`CineVaultStudio-Android-Universal.apk`**（支持 Android 7.0+ 全架构通用）。
2. **导入电脑端数据**：
   - **方式 A（推荐，含封面）**：在 Windows 端点击「📦 同步包 (.cvpack)」导出 `cinevault_sync.cvpack` 并发送到手机。在安卓 App 中点击底部 **「📥 导入」** 选择该 `.cvpack` 文件，即可一键导入全部元数据、半星评分、标签与本地封面图。
   - **方式 B（直接导入数据库）**：也支持直接选择从电脑端拷贝的 `cinevault_library.db` 文件进行数据导入。
3. **本地目录哈希对齐与播放**：
   - 点击底部 **「📂 扫描」** 选择手机或 SD 卡里的视频文件夹，安卓端内置与电脑端完全一致的 **BLAKE2b-128 三段 64KB 极速复合哈希 (`cvh1_blake2b_3x64k`)**，自动将导入的影片记录对齐到手机本地路径。
   - 点击 **「▶ VLC 播放」** 可直接唤起 **VLC for Android**（或系统播放器）播放本地/SMB 视频，也支持内置播放器播放。

---

## 🤖 AI 补全与标签校对工作流 (AI Enrichment Workflow)

1. 在网页界面点击 **「✨ AI 补全与新厂牌收录」**。
2. 选择导出模式（`incomplete` 综合补全 或 `tags_only` 仅校对标签），点击 **「💾 写入本批到 AI_KEYWORD_DB.md」**（每批 25 条）。
3. 使用任意 CLI AI 助手（Claude Code / Gemini CLI / Codex CLI / Cursor Agent）在程序目录中参考 `AI_ENRICHMENT_GUIDE.md` 就地修改 `AI_KEYWORD_DB.md` 并保存。
4. 回到界面点击 **「📂 从根目录 AI_KEYWORD_DB.md 导入结果」**，系统自动安全合并标签、永久收录新厂牌并刷新资料库。

---

## 🛠️ 本地测试与打包 (Development & Build)

### 运行单元测试
```bash
python -m unittest discover -s tests -p "test_*.py" -v
```

### 本地编译 Windows 单文件 `.exe`
```bash
pip install pyinstaller
scripts\build_windows_exe.bat
```
编译产物将生成于 `dist\CineVaultStudio.exe`。

### GitHub Actions 自动编译与发布 Release
本仓库已配置 [`.github/workflows/release.yml`](.github/workflows/release.yml)：
- 每次推送到 `main` 或提交 PR 时自动运行全套单元测试。
- 推送 `v*` 格式标签（例如 `git tag v1.0.0 && git push origin v1.0.0`）或在 Actions 页面手动触发时，GitHub Actions 将在 `windows-latest` 环境中自动完成：
  1. 运行全套单元测试
  2. 使用 PyInstaller 编译 `CineVaultStudio.exe`
  3. 执行 `CineVaultStudio.exe --self-check` 冒烟自检
  4. 打包绿色便携版 `CineVaultStudio_Portable.zip`（含 `CineVaultStudio.exe` 与 `AI_ENRICHMENT_GUIDE.md`）
  5. 自动创建并发布 GitHub Release

---

## 📂 目录结构 (Project Layout)

```text
CineVault-Studio/
├── .github/workflows/release.yml   # GitHub Actions CI & Windows/Android 自动编译打包
├── android/                        # Android 通用版原生工程 (Kotlin + WebView + SQLite + BLAKE2b)
├── AI_ENRICHMENT_GUIDE.md          # CLI AI 模型元数据与标签校对完整规范指南
├── ARCHITECTURE.md                 # 核心架构与不变量设计文档
├── INTERFACE_CONTRACTS.md          # REST API、SQLite、MCP 与 .cvpack 接口契约
├── LICENSE                         # MIT 开源许可证
├── README.md                       # 项目说明文档
├── requirements.txt                # 可选打包与增强依赖（核心运行时零依赖）
├── docs/ui_concepts/               # 双主题 UI 设计概念图
├── scripts/
│   ├── build_windows_exe.bat       # Windows 单文件 PyInstaller 打包脚本
│   └── run_dev.py                  # 本地服务启动与自检入口
├── src/
│   ├── core/                       # 零依赖核心引擎（模型、复合哈希、解析、刮削、AI 桥接、同步包、播放器）
│   ├── adapters/                   # 本地适配器（SMB/磁盘扫描、SQLite、在线刮削、FFmpeg/时长探测、MCP、HTTP 服务）
│   └── ui/index.html               # 双主题双语响应式 Web/PWA 前端界面
└── tests/
    ├── test_core.py                # 核心引擎单元测试
    └── test_tasks.py               # 适配器与 REST API 集成测试
```

---

## 📄 开源协议 (License)

本项目基于 [MIT License](LICENSE) 开源。
