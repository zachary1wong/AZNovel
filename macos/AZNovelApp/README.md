# AZNovel Mac App Shell

这个目录提供一个轻量 macOS AppKit 壳子，用来并行启动多个 AZNovel CLI 工作线。

核心原则：

- App 不重新实现 LLM API，不直接调用 OpenAI 或 Anthropic。
- 每条工作线都通过 `python3 -m aznovel ...` 启动同一份 CLI。
- 打包时会把当前源码目录写入 App 资源，Finder 启动时也会通过 `PYTHONPATH` 使用这份源码。
- 每条工作线是独立进程，所以可以同时为多部小说运行不同项目目录和不同 `--profile`。

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

App 中的“自定义 CLI 参数”可以输入任意 CLI 参数，例如：

```text
write --chapter 3 --mode fast
auto-run --target 30
export --format epub,pdf,docx
```
