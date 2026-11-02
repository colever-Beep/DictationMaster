# 听写助手 DictationMaster

对标希沃白板听写功能的本地独立听写软件。基于 **PySide6 + qfluentwidgets（Fluent 风格）**，
语音由 **edge-tts** 合成，断网自动降级系统离线语音引擎；所有用户数据保存在
`%LOCALAPPDATA%\DictationMaster`，不写安装目录、不联网上传任何内容。

## 功能一览

- **听写**：选词表 → 调参数（遍数 / 间隔 / 语速 / 音色模式 / 纸笔模式…）→ 听前信息确认弹窗 → 3-2-1 倒计时 → 逐词报读
- **语音**：edge-tts 在线合成（可选 **Kokoro 离线引擎** 兜底）；听写前后可播报本次信息与结束提示
- **词表**：新建 / 编辑 / 导入（txt / csv / xlsx）/ 内置教材按单元导入 / 导出 txt+csv
- **布置任务**：教师按选取词范围 + 截止日期生成任务，次日课代表一键执行
- **跨电脑同步**：把布置任务上传到 GitHub 仓库的 `tasks/` 目录，教室端一键拉取（零服务器）
- **复盘**：结果表逐词标记（写错 / 已掌握）→ 错题本累计 → 一键重练错词 → 历史记录与 CSV 导出
- **设置**：主题 / 默认音色（可试听）/ 代理 / 合成并发数 / TTS 引擎 / 语音播报 / GitHub 同步 / 缓存目录
- **快捷键**：`Space` 开始/暂停 · `←/→` 上/下一个 · `R` 重读 · `Esc` 停止

## 跨电脑分发听写任务（GitHub 同步）

用仓库当「传输介质」，不需要服务器：

1. 建一个仓库（私有仓库更合适），在仓库里**创建任务目录**——本仓库已自带 [`tasks/`](tasks/README.md)，
   即「用户数据文件夹」，存放听写任务 JSON；也可在「设置 → GitHub 同步 → 初始化目录」一键生成；
2. 生成 Personal Access Token（细粒度 PAT，仅授权该仓库 `Contents: Read and write`）；
3. 教师端：设置页填 `owner / repo / branch / Token / 任务目录` → 测试连接 → 布置任务时「上传到 GitHub」；
4. 教室端：填同一套设置（需 Token，私有仓库）→「管理布置」→「从 GitHub 拉取」。

「上传默认设置」可控制：**布置后自动上传**、**上传时覆盖同名任务**（关闭则保留教室端已有内容）。

> 仓库结构：代码在根目录，听写任务在 `tasks/`（用户数据），本地运行数据仍在
> `%LOCALAPPDATA%\DictationMaster`，不入库。

## 开发运行

```
cd D:\VScode\c\tingxie
python main.py
```

依赖（全局 Python 3.14 环境）：

```
pip install PySide6 PySide6-Fluent-Widgets edge-tts -i https://pypi.tuna.tsinghua.edu.cn/simple
```

运行测试（无显示器环境可用 offscreen）：

```
set QT_QPA_PLATFORM=offscreen
python -m pytest tests/ -q
```

## 打包发布（PyInstaller onedir）

```
build.bat
```

脚本会：检查/安装 PyInstaller → 按 `app.spec` 打包 → **自检 Qt multimedia 插件**
（缺失会导致打包后没有声音）→ 输出 `dist\DictationMaster\`。

发布物为整个 `dist\DictationMaster\` 文件夹（入口 `DictationMaster.exe`），
复制 / 压缩到任意未装 Python 的 Windows 机器解压即用。

手动打包命令：

```
python -m PyInstaller app.spec --noconfirm
```

## 更换应用图标

1. 准备一个正方形 PNG（建议 256×256 以上），命名为 `icon.png`；
2. 重新生成多尺寸 ico：

   ```
   python tools\make_icon.py        REM 按需修改 tools/make_icon.py 里的绘制逻辑
   ```

   或用任意工具把你的 PNG 转成 `assets\app.ico`（含 16/24/32/48/64/128/256 尺寸最佳）；
3. 重新执行 `build.bat`。

## 数据目录

| 内容 | 路径 |
| --- | --- |
| 配置 | `%LOCALAPPDATA%\DictationMaster\config.json` |
| 词表 | `%LOCALAPPDATA%\DictationMaster\wordlists\`（首次启动种入内置词表，不覆盖自建） |
| 听写布置任务 | `%LOCALAPPDATA%\DictationMaster\assignments\` |
| 历史 / 错题本 | `%LOCALAPPDATA%\DictationMaster\data\dictation.db`（SQLite） |
| 音频缓存 | `%LOCALAPPDATA%\DictationMaster\cache\`（可在设置页更改） |
| 日志 | `%LOCALAPPDATA%\DictationMaster\logs\app.log` |
| 内置教材（启动时复制） | `%LOCALAPPDATA%\DictationMaster\textbooks\` |
| 仓库内的任务目录（同步用） | `<仓库>/tasks/` |

## 已知限制

- edge-tts 需 **7.3.1+**（微软 2026-10 起启用 v2 鉴权令牌，旧版会 403）；
- edge-tts 不支持 SSML，多音字别名暂按纯文本报读；
- Kokoro 离线引擎为可选依赖（`pip install kokoro misaki[zh]`），首次使用需下载模型；
- 「检查更新」为占位按钮，当前为离线分发；
- 报读提示音为单音 880Hz 简化版。
