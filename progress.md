# AZNovel Mac App Progress

更新时间：2026-06-02

## 当前目标

把 AZNovel 从简单 CLI 启动器升级为可用的 macOS 多流水线小说写作工作台，并安装到 `/Applications/AZNovel.app`。

核心要求：

- API 调用必须和 CLI 版本完全一致，Mac App 只作为壳子调用同一套 `aznovel` CLI。
- 支持多部小说并行写作。
- 每条流水线可选择独立项目目录和独立 LLM profile。
- 每条流水线内需要有 LLM 能力，后续用聊天式自然语言继续下指令。
- 多流水线布局为横向分屏：1 条占满，2 条左右分屏，3 条三列，4 条以上水平滚动且每条仍保持约 1/3 窗口宽度。
- 流程阶段包括：方向和参数定义、大纲输出和迭代、逐章写作、整书校验和精修、产出 EPUB。
- 高频标准操作要抽出按钮，例如重写某章、批量角色改名、整书精修、导出 EPUB。
- 窗口宽度不得超过当前设备可见屏幕宽度，不能打开后跑到屏幕外。
- LLM profile 不仅要能选择，还要能在 Mac App 中编辑。
- 顶部大标题区域需要去掉，包括 App 图标、`AZNovel` 大标题、副标题、CLI 路径和 Source 路径。

## 已完成

- CLI 版本改动已单独提交并推送到 GitHub。
  - 提交：`c89aee4 Enhance novel workflow CLI`
  - 验证：`python3 -m pytest`，结果 `61 passed`

- 初版 macOS App 壳子已单独提交并推送到 GitHub。
  - 提交：`a17588f Add macOS app shell`
  - 安装路径：`/Applications/AZNovel.app`
  - 壳子调用方式：`/usr/bin/python3 -m aznovel`
  - 通过 `PYTHONPATH=/Users/wangzesen/Documents/Projects/AZNovel` 指向当前源码，保证 API provider 路径和 CLI 一致。

- App 图标已生成并接入构建脚本。
  - 源图：`macos/AZNovelApp/Assets/AppIcon.png`
  - 构建脚本会生成：`AppIcon.icns`
  - `Info.plist` 已设置：`CFBundleIconFile = AppIcon.icns`
  - 图标白底问题已处理：源 PNG、icns 解包图、系统识别图标四角 alpha 均为 `0`。

- 初步窗口问题已排查。
  - 用户确认窗口实际能显示。
  - 主要问题不是无窗口，而是旧界面只是命令启动器，内容太少，不符合目标产品形态。

- 重构后的 Swift 代码已完成首次编译验证。
  - 命令：`macos/AZNovelApp/build_and_install.sh --no-install`
  - 结果：编译成功，构建出 `build/macos/AZNovel.app`

- Swift 编译警告已清理。
  - 已将阶段流程区域的废弃 `NSBox.BoxType.secondary` 改为 `primary`。
  - 再次执行 `macos/AZNovelApp/build_and_install.sh --no-install`，结果编译通过且无警告。

- 最新反馈对应的代码改动已完成并通过编译。
  - 已移除顶部大标题区域：不再显示 App 图标、`AZNovel` 大标题、副标题、CLI 路径和 Source 路径。
  - LLM 配置区已改为紧凑工具条。
  - 已增加 `编辑 Profile` 能力，可读写 `~/.aznovel/llm_profiles.json`。
  - 窗口初始宽度和最小宽度已改为基于当前屏幕 `visibleFrame` 动态计算，避免超出屏幕。
  - 命令：`macos/AZNovelApp/build_and_install.sh --no-install`
  - 结果：编译通过且无警告。

- 最新版 App 已重新安装并启动。
  - 命令：`macos/AZNovelApp/build_and_install.sh`
  - 安装路径：`/Applications/AZNovel.app`
  - 进程验证：`/Applications/AZNovel.app/Contents/MacOS/AZNovel` 已运行。
  - 旧一轮窗口尺寸验证：当前主屏可见宽度约 2880px，AZNovel 窗口宽度约 2617px，未超出屏幕；但用户实际截图显示在 MacBook Air M1 的当前缩放/桌面布局下仍然过宽。

- 窗口尺寸限制进一步加固。
  - 已设置 `window.maxSize`，最大宽度不再跟随整屏放大到极限，而是收紧到约 `960pt`。
  - 已禁用窗口恢复，并在启动、重新打开和启动后延迟校正时强制回到安全窗口 frame。
  - 安装脚本现在会先停止旧的 `AZNovel` 进程并清除 `com.aznovel.launcher.savedState`，避免继续看到旧窗口尺寸。

- MacBook Air M1 窗口尺寸重新适配已完成并验证。
  - 默认窗口宽度收紧到约 `900pt`，高度收紧到约 `680pt`。
  - 流水线内部改为独立纵向滚动，避免按钮区和日志区把主窗口高度撑到屏幕外。
  - 顶部 LLM profile 摘要和流水线内 profile 详情已设置为单行截断，避免长 URL/profile 文本撑宽窗口。
  - 流水线列宽计算已改为最小约 `260pt`，保持 1/2/3 条流水线的分屏逻辑，4 条以上继续横向滚动。
  - 当前实测桌面 bounds：`1440 × 900pt`。
  - 当前实测 AZNovel 窗口：位置 `270,95`，尺寸 `900 × 682pt`。
  - 当前安装包版本：`CFBundleVersion = 20260602170712`。

- 流水线开关和新建小说项目入口已补齐。
  - 每条流水线顶部新增明确的 `关闭流水线` 按钮。
  - 关闭正在运行的流水线时会先弹窗确认，并停止底层 CLI 进程。
  - 小说目录区域改为独立纵向布局，不再把目录输入框和按钮挤在同一行。
  - 新增 `新建小说项目` 按钮：选择新项目目录后创建目录、填入路径，并自动启动 `aznovel init` 的方向定义流程。
  - 新增 `选择已有项目` 和 `打开目录` 按钮，入口文案更直观。
  - 占位说明已更新，明确第一步是新建小说项目或选择已有项目。
  - 命令：`macos/AZNovelApp/build_and_install.sh --no-install`
  - 结果：编译通过且无警告。
  - 已重新安装并打开 `/Applications/AZNovel.app`。
  - 当前安装包版本：`CFBundleVersion = 20260602174709`。
  - 当前实测 AZNovel 窗口：位置 `270,95`，尺寸 `900 × 682pt`。

- Computer-use 已启用并用于真实窗口验证。
  - 已通过 Computer-use 直接读取 `/Applications/AZNovel.app` 的窗口、辅助功能树和视觉截图。
  - 确认上一版不是旧包问题，而是每条流水线内部 `NSScrollView` 造成控件存在于辅助功能树、但视觉区域空白。
  - 已撤掉流水线内部滚动层，恢复直接布局。
  - 已确认视觉上能看到 `关闭流水线`、`新建小说项目`、`选择已有项目`、`打开目录`、`方向`、`聊天`、阶段按钮和日志区。
  - 命令：`macos/AZNovelApp/build_and_install.sh --no-install && macos/AZNovelApp/build_and_install.sh && open -a /Applications/AZNovel.app`
  - 结果：编译通过、安装成功、Computer-use 验证可见。
  - 当前安装包版本：`CFBundleVersion = 20260602181014`。

- README 已更新。
  - 根目录 `README.md` 已改为说明横向分屏流水线、profile 编辑、chat 会话和阶段按钮。
  - `macos/AZNovelApp/README.md` 已同步新版 Mac App 工作台能力。

- 2026-06-02 晚间布局/稳定性修复已完成并安装验证。
  - 修复一次启动即退出问题：根因是 `logColumn` / `workflowPanel` 属性被局部变量遮蔽，`setPreferredWidth()` 访问未初始化属性导致 `EXC_BREAKPOINT`。
  - 默认窗口改为最大非全屏打开，当前 MacBook Air M1 实测窗口约 `1424 × 789pt`。
  - 顶部 LLM 配置区改成 30pt 工具条，减少垂直占用。
  - 根布局改为手写 Auto Layout：顶部工具条固定，流水线工作区填满窗口剩余区域。
  - 日志区改为动态高度，并在输出追加后异步滚到最新行。
  - 阶段流程面板已从“每阶段一行 3 个按钮”改为“每阶段单列按钮”，面板宽度从约 `224pt` 收窄到约 `132pt`。
  - 修复添加第 2 条流水线触发崩溃的问题：移除了对 `bodyStack` 子视图的运行期拆装重排。
  - 安装脚本已增强旧实例清理：先 `osascript quit`，再按完整 `/Applications/AZNovel.app/Contents/MacOS/AZNovel` 路径 kill 残留进程，必要时 `kill -9`。
  - 验证：`macos/AZNovelApp/build_and_install.sh` 编译安装成功，`CFBundleVersion = 20260602202327`。
  - Computer-use 验证：1 条流水线时日志区占主要面积；点击 `添加流水线` 后 2 条流水线左右分屏成功，App 未崩溃，两个流程面板均为单列窄条。

## 正在进行

正在继续验证最新反馈对应的新版 App：

- 把主界面从纵向命令卡片改成横向流水线分屏。
- 顶部大标题/图标/CLI 路径区域已去掉。
- LLM 配置区域已保留并增强为可编辑 profile。
- MacBook Air M1 默认窗口尺寸已收紧并完成安装后实测。
- 每条流水线已补充明确的关闭按钮。
- 每条流水线已补充新建小说项目入口，新项目会直接进入 `aznovel init`。
- LLM 配置读取：
  - `~/.aznovel/config.json`
  - `~/.aznovel/llm_profiles.json`
- 每条流水线加入独立 profile 下拉框。
- 每条流水线启动独立 `aznovel chat` 进程。
- GUI 输入框把自然语言指令写入该进程 stdin。
- 输出区读取 stdout/stderr，并显示该流水线自己的对话记录。
- 加入五阶段按钮区：
  - 方向参数：方向定义、项目状态、梳理参数
  - 大纲迭代：生成大纲、修改大纲、查看大纲
  - 逐章写作：下一章、连写 3 章、重写某章
  - 校验精修：审查最新、安全修复、终稿精修
  - 产出：EPUB、多格式、角色改名
  - 当前布局为单列按钮，优先保证多流水线时日志区宽度。

## 待完成

- 验证 UI：
  - 默认 1 条流水线占满工作区。已通过 Computer-use 验证。
  - 2 条流水线左右分屏。已通过 Computer-use 验证。
  - 3 条流水线三列。
  - 4 条以上出现水平滚动，每条线仍保持约 1/3 宽度。
  - 最小窗口宽度不破坏分屏逻辑，目前已通过窗口尺寸约束和流水线内部滚动降低撑宽风险，仍需肉眼验证多流水线状态。
  - Computer-use 已可用，后续 UI 视觉验证优先使用 Computer-use。
- 验证 LLM profile：
  - 顶部能展示全局默认配置和 profile 列表。
  - 每条流水线能选择不同 profile。
  - Mac App 内可以编辑 profile 并写回 `~/.aznovel/llm_profiles.json`。
  - 启动命令包含正确的 `--profile <name>`。
- 验证聊天式交互：
  - `启动聊天` 能启动 `python3 -m aznovel [--profile name] chat`。
  - 输入自然语言能写入 stdin。
  - 快捷按钮能把标准自然语言命令送入同一 chat 会话。
- 通过后提交并推送 GitHub。

## 当前未提交改动

- `macos/AZNovelApp/Sources/AZNovelApp.swift`
- `macos/AZNovelApp/build_and_install.sh`
- `macos/AZNovelApp/README.md`
- `macos/AZNovelApp/Assets/AppIcon.png`
- `progress.md`
- `ToDoList.md`
- `tmp/现代商战悬疑短篇/`

## 已知风险

- `aznovel init` 是 CLI 交互流程，GUI 中作为“方向定义”阶段启动时，需要确认 stdin/stdout 交互体验足够可用。
- `aznovel chat` 的输出包含 Rich/ANSI 动态显示，GUI 已做 ANSI 清理，但复杂 spinner/进度输出仍需真实验证。
- 部分快捷按钮只是向 chat 发送标准自然语言命令，依赖 CLI chat 的意图识别逻辑。
- 当前新版 Swift 代码已能编译并完成安装后窗口尺寸验证；profile 编辑、chat stdin/stdout 和多流水线肉眼交互仍需继续验证。
- LLM profile 编辑需要写入 `~/.aznovel/llm_profiles.json`，必须避免破坏已有配置和 API Key。

## 下一步

1. 验证顶部区域已移除后的实际视觉效果。
2. 验证 profile 编辑弹窗可保存并刷新列表。
3. 验证分屏、profile、chat stdin/stdout 和阶段按钮。
4. 通过后提交并推送 GitHub。
5. 每完成一个步骤更新本文件。
