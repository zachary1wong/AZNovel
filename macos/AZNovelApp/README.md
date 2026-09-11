# AZNovel Mac App Shell

这个目录提供一个轻量 macOS AppKit 壳子，用来并行运行多个 AZNovel CLI 小说流水线。

核心原则：

- App 不重新实现 LLM API，不直接调用 OpenAI 或 Anthropic。
- 每条流水线都通过 `python3 -m aznovel ...` 启动同一份 CLI。
- 打包时会把当前源码目录写入 App 资源，Finder 启动时也会通过 `PYTHONPATH` 使用这份源码。
- 打包时会从 `Assets/AppIcon.png` 生成 macOS `AppIcon.icns`。
- 每条流水线是独立进程，所以可以同时为多部小说运行不同项目目录和不同 `--profile`。
- App 内可查看和编辑 `~/.aznovel/llm_profiles.json` 中的 LLM profile。

界面能力：

- 横向分屏：1 条流水线占满窗口，2 条左右分屏，3 条三列，4 条以上水平滚动。
- 每条流水线可独立选择项目目录和 LLM profile。
- 每条流水线启动独立 `aznovel chat` 会话，输入框会把自然语言指令写入该会话。
- 阶段按钮覆盖方向参数、大纲迭代、逐章写作、整书校验精修、导出 EPUB。

构建并安装到 `/Applications`：

```bash
macos/AZNovelApp/build_and_install.sh
```

只构建不安装：

```bash
macos/AZNovelApp/build_and_install.sh --no-install
```

可用环境变量：

- `AZNOVEL_PYTHON`：指定 Python 解释器路径，默认使用 `command -v python3`。
- `AZNOVEL_INSTALL_DIR`：指定安装目录，默认 `/Applications`。

App 仍然只是一层壳，实际写作、审查、改名、导出等能力都来自同一份 CLI。
