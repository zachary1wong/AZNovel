# AZNovel

AI辅助中文小说写作CLI工具。支持网文、文学和短剧剧本三类题材，通过对话式交互完成创作全流程。

## 功能特点

- **多题材支持**：
  - 网文：玄幻/仙侠/都市/历史/奇幻/科幻
  - 文学：纯文学/推理悬疑/言情文学/科幻文学
  - 短剧：逆袭爽剧/甜宠/虐恋/复仇/穿越重生/都市情感/古装
- **6步写作流水线**：预检 → 契约刷新 → 上下文组装 → 初稿生成 → 审查 → 提交
  - 初稿生成严格遵循大纲，确保正文覆盖大纲指定的角色、事件和场景
  - 审查包含**大纲合规性检查**（第7维度），偏离大纲的内容会被标记为 critical
- **对话式初始化**：AI引导用户构思设定、生成大纲；支持导入已有设定/小说/大纲
- **自然语言操作**：用对话方式驱动写作、审查、重写、精修等操作（支持 21 种操作）
- **章节精修**：逐段润色文字，修复语病和不通顺，不改剧情结构；支持单章/范围/全部精修
- **反推大纲**：从已写章节反推大纲，方便检阅整本书结构
- **需求驱动大纲生成**：可指定创作需求，AI严格按需求设计大纲
- **章节重写**：支持修改已有内容，自动检测是否影响后续章节
- **角色改名**：受控替换角色名和小名/昵称/称谓，同步正文、大纲、设定、审查报告，生成审计报告
- **完稿流程**：终检安全修复 + 终稿精修，一键收尾
- **无人值守写作**：从当前进度自动补写到目标章数，失败自动修复候选稿
- **LLM配置管理**：多配置支持，可并发运行不同项目
- **/btw 非阻断查询**：写作过程中可查看项目状态

## 安装

### 从源码安装

```bash
git clone https://github.com/zachary1wong/AZNovel.git
cd AZNovel
pip install -e .
```

### 依赖

- Python 3.9+
- OpenAI API 或 Anthropic API（或其他兼容API）

## 快速开始

### 1. 配置LLM

首次使用需要配置LLM API：

```bash
aznovel config init
```

按提示输入：
- API提供商（openai/anthropic）
- 模型名称
- API Key
- Base URL（如使用自定义API端点）

### 2. 初始化项目

在空目录中初始化新项目：

```bash
mkdir my-novel
cd my-novel
aznovel init
```

AI会引导你完成：
1. 确定小说标题、题材
2. 设定主角信息（姓名、身份/境界、目标、金手指）
3. 规划写作规模（总字数、每章字数）
4. 生成大纲
5. 创建项目结构

初始化过程中还可以导入已有内容：
- **导入设定**：从文件导入世界观、人物设定，AI自动分析整理
- **导入小说**：从文件导入已写好的章节，AI提取角色、剧情线
- **导入大纲**：从文件导入大纲

### 3. 写作章节

```bash
# 写第1章
aznovel write --chapter 1

# 指定大纲文件
aznovel write --chapter 1 --outline 大纲/第1章.md

# 覆盖已有章节
aznovel write --chapter 1 --overwrite

# 快速模式（跳过审查）
aznovel write --chapter 2 --mode fast

# 最小模式（仅格式检查）
aznovel write --chapter 3 --mode minimal
```

### 4. 精修章节

```bash
# 精修指定章节
aznovel polish --chapter 3

# 精修章节范围
aznovel polish --start 1 --end 5

# 精修全部章节
aznovel polish --all

# 逐段精修模式（更仔细但更慢）
aznovel polish --chapter 3 --careful
```

### 5. 导出全书

将所有已写章节合并导出为单个文件，默认输出到 `导出/`：

```bash
# 导出 EPUB
aznovel export --format epub

# 一次导出多个格式
aznovel export --format epub,pdf,docx

# 导出全部支持格式
aznovel export --format all

# 指定输出目录或单格式输出文件
aznovel export --format docx --output dist
aznovel export --format pdf --output dist/我的小说.pdf
```

支持格式：`epub`、`pdf`、`docx`、`mobi`。MOBI 导出需要本机安装 Calibre 的 `ebook-convert` 或 Amazon `kindlegen`。

### 6. 对话模式

进入AI对话模式，用自然语言操作：

```bash
aznovel chat
```

对话示例：
```
你 > 写下一章
你 > 连续写3章
你 > 审查第3章
你 > 审查最新一章
你 > 显示项目状态
你 > 查看大纲
你 > 重写第2章，把开头改得更吸引人
你 > 精修第5章
你 > 反推大纲
你 > 导出全书为 epub，pdf，docx
你 > 生成大纲，加入一个反派角色
你 > 修改大纲，第3章要加入一场战斗
你 > 更新设定，主角境界提升到筑基
你 > 把角色张老三改名为张小明
你 > 终检安全修复全书
你 > 终稿精修全书
你 > 完稿流程
你 > 无人值守写到第 80 章
```

对话模式支持 21 种操作：
| 操作 | 说明 |
|------|------|
| `write_next` | 写下一章 |
| `write_chapter` | 写指定章节 |
| `write_batch` | 连续写多章 |
| `review_chapter` | 审查指定章节 |
| `review_latest` | 审查最新一章 |
| `repair_chapter` | 按审查报告局部修复章节 |
| `show_status` | 显示项目状态 |
| `show_chapter` | 查看章节内容 |
| `update_setting` | 更新设定文件 |
| `generate_outline` | 重新生成大纲 |
| `revise_outline` | 修改大纲 |
| `show_outline` | 显示当前大纲 |
| `rewrite_chapter` | 重写章节 |
| `reverse_outline` | 反推大纲 |
| `polish_chapter` | 精修章节 |
| `final_safe_repair` | 终检安全修复全书硬逻辑问题 |
| `final_polish` | 终稿精修，只修出戏表达和衔接薄点 |
| `finalize_book` | 完稿流程：先终检安全修复，再终稿精修 |
| `rename_character` | 角色改名（同步正文、大纲、设定、审查报告） |
| `auto_run_book` | 无人值守全流程：补写到目标章数并产出终稿精修稿 |
| `export_book` | 导出全书为单个文件 |

### 7. 反推大纲

从已写章节反向生成大纲，不覆盖原大纲：

```bash
aznovel reverse-outline
```

### 8. 需求驱动大纲生成

在对话模式中，可以指定创作需求让AI严格按需求生成大纲：

```
你 > 生成大纲，加入一个反派角色
你 > 修改大纲，第3章要加入一场战斗
你 > 重新生成大纲，要求：主角在第5章获得新能力
```

AI会将用户需求标记为最高优先级，大纲的每一卷都有完整的逐章明细。

### 9. 无参数启动

```bash
# 在项目目录内：自动进入对话模式
aznovel

# 在非项目目录：自动进入初始化流程
aznovel

# 指定LLM配置
aznovel --profile my-config
```

## 命令说明

### init - 初始化项目

```bash
# 对话式初始化
aznovel init

# 直接指定参数
aznovel init -t "我的小说" -g 都市 -p 张三 --identity 修仙者 --goal 飞升 --golden-finger 系统面板

# 在指定目录初始化
aznovel init ./my-project
```

选项：
- `-t, --title`：小说标题
- `-g, --genre`：题材类型
- `-p, --protagonist`：主角姓名
- `--identity`：主角初始身份/境界
- `--goal`：主角初始目标
- `--golden-finger`：金手指/特殊能力

### write - 写作章节

```bash
aznovel write -c <章节号> [-m default|fast|minimal] [-o <大纲路径>] [-p <配置名>] [--overwrite]
```

选项：
- `-c, --chapter`：章节编号（必填）
- `-m, --mode`：模式（default/fast/minimal，默认default）
- `-o, --outline`：大纲文件路径
- `-p, --profile`：LLM配置名称
- `--overwrite`：覆盖已有章节

模式说明：
- `default`：完整流水线（初稿→审查→润色→再审查）
- `fast`：快速模式（初稿→轻量审查）
- `minimal`：最小模式（仅格式检查）

### polish - 精修章节

```bash
# 精修指定章节
aznovel polish -c <章节号> [--careful] [-p <配置名>]

# 精修章节范围
aznovel polish -s <起始> -e <结束> [-p <配置名>]

# 精修全部章节
aznovel polish -a [-p <配置名>]
```

选项：
- `-c, --chapter`：精修指定章节
- `-s, --start`：起始章节号
- `-e, --end`：结束章节号
- `-a, --all`：精修全部章节
- `--careful`：逐段精修模式，更仔细但更慢（默认批量10段）
- `-p, --profile`：LLM配置名称

### review - 审查章节

```bash
aznovel review -c <章节号> [-d 维度1,维度2] [-p <配置名>]
```

选项：
- `-c, --chapter`：章节编号（必填）
- `-d, --dims`：审查维度（逗号分隔）
- `-p, --profile`：LLM配置名称

审查维度：
- `consistency`：前后一致性
- `timeline`：时间线逻辑
- `characterization`：角色塑造
- `plot`：剧情逻辑
- `style`：文风连贯性
- `ai_flavor`：AI味检测
- `outline_compliance`：大纲合规性（检查是否偏离大纲要求）

### rewrite - 重写章节

```bash
aznovel rewrite -c <章节号> -m "修改要求" [--cascade] [--mode default|fast|minimal] [-p <配置名>]
```

选项：
- `-c, --chapter`：章节编号（必填）
- `-m, --modification`：修改要求描述（必填）
- `--cascade`：强制删除后续章节（不询问）
- `--mode`：模式（default/fast/minimal，默认default）
- `-p, --profile`：LLM配置名称

如果修改影响后续章节，会提示删除后续章节。使用 `--cascade` 强制删除。

### reverse-outline - 反推大纲

```bash
aznovel reverse-outline [-p <配置名>]
```

从已写章节反推大纲，方便检阅整本书结构。不会覆盖原大纲。

### safe-repair - 终检安全修复

```bash
# 全书终检硬逻辑问题，只应用可验证的小补丁
aznovel safe-repair

# 指定章节列表
aznovel safe-repair -c 6,8,10

# 只生成候选和报告，不覆盖正文
aznovel safe-repair --dry-run
```

跨章节终检角色、时间线、设定一致性等硬逻辑问题，只应用可验证的小补丁，不整章重写。

### final-polish - 终稿精修

```bash
# 全书终稿精修：只修出戏表达、薄弱过桥和小型文字瑕疵
aznovel final-polish

# 指定章节列表
aznovel final-polish -c 7,8,10

# 只生成候选和报告，不覆盖正文
aznovel final-polish --dry-run
```

完稿前最后一轮润色，不改剧情结构，只做可验证的微调。

### finalize - 完稿流程

```bash
aznovel finalize [--dry-run] [-p <配置名>]
```

一键跑完稿流程：先执行 `safe-repair` 全书硬逻辑修复，再执行 `final-polish` 终稿精修。

### rename-character - 角色改名

```bash
# 基本改名
aznovel rename-character -f 张老三 -t 张小明

# 带称谓映射（小名/昵称一并替换）
aznovel rename-character -f 张老三 -t 张小明 -a 三哥=明哥,老三=小明

# 只生成变更报告，不覆盖任何文件
aznovel rename-character -f 张老三 -t 张小明 --dry-run
```

受控更新角色名、小名、昵称和项目实体信息，同步正文、大纲、设定、状态、契约和审查报告，并生成 before/after 审计报告。

### auto-run - 无人值守全流程

```bash
# 写到项目配置的目标章数
aznovel auto-run

# 显式指定目标章数
aznovel auto-run -t 80

# 每章候选稿最多自动修复 3 次
aznovel auto-run -t 80 --max-repair-attempts 3
```

从当前进度一口气写到目标章数，期间失败自动修复候选稿，最后自动跑终检和终稿精修，全程不需要人工干预。

### export - 导出全书

```bash
aznovel export [-f epub|pdf|mobi|docx|all] [-o 输出文件或目录]
```

选项：
- `-f, --format`：导出格式，可用逗号分隔多个格式，默认 `epub`
- `-o, --output`：输出文件或目录；多格式导出时必须指定目录

默认导出到 `导出/<小说标题>.<格式>`。MOBI 需要本机安装 `ebook-convert` 或 `kindlegen`。

### chat - 对话模式

```bash
aznovel chat [-f] [-p <配置名>]
```

选项：
- `-f, --fast`：快速模式（跳过审查）
- `-p, --profile`：LLM配置名称

### status - 显示状态

```bash
aznovel status
```

### config - 配置管理

```bash
# 初始化配置
aznovel config init

# 查看配置
aznovel config get
aznovel config get api_key

# 设置配置
aznovel config set model gpt-4o
aznovel config set api_key YOUR_KEY -g

# 查看已保存的LLM配置
aznovel config profiles
```

选项：
- `-g, --global`：保存到全局配置（set操作时使用）

## LLM配置管理

支持保存多个LLM配置，方便切换：

```bash
# 查看已保存配置
aznovel config profiles

# 使用指定配置
aznovel write -c 1 -p gpt4o
aznovel chat -p claude
aznovel polish -c 3 -p claude
```

## 并发使用

支持多个session同时运行不同项目：

```bash
# 终端1：用配置A写小说1
cd novel-1
aznovel write -c 1 -p config-a

# 终端2：用配置B写小说2
cd novel-2
aznovel write -c 1 -p config-b
```

### Mac App 壳子

仓库内提供一个轻量 macOS App 壳子，可以在一个窗口里并行运行多条小说流水线。它不重新实现 API，而是直接调用同一套 CLI：

```bash
macos/AZNovelApp/build_and_install.sh
```

安装后可在 `/Applications/AZNovel.app` 打开。Mac App 支持：

- 横向分屏流水线：1 条占满窗口，2 条左右分屏，3 条三列，4 条以上水平滚动。
- 每条流水线独立选择小说项目目录和 LLM profile。
- 在 App 内查看、编辑 `~/.aznovel/llm_profiles.json` 中的 LLM profile。
- 每条流水线启动独立 `aznovel chat` 会话，后续可继续用自然语言下指令。
- 阶段按钮：方向参数、大纲迭代、逐章写作、整书校验精修、导出 EPUB。

## /btw 命令

在写作过程中，可以输入 `/btw` 命令查看信息，不阻断当前操作：

```
/btw status      # 查看项目状态
/btw progress    # 查看当前执行步骤
/btw chapter 3   # 查看第3章前500字
/btw help        # 显示帮助
```

## 项目结构

```
my-novel/
├── .aznovel/          # 项目内部数据
│   ├── state.json     # 项目状态
│   ├── config.json    # 项目配置
│   ├── commits/       # 提交记录
│   └── contracts/     # 契约文件
├── 设定集/            # 世界观、人物设定
├── 大纲/              # 故事大纲
├── 正文/              # 章节正文
├── 导出/              # 全书导出文件
└── 审查报告/          # 审查报告
```

## 支持的题材

### 网文类
- 玄幻、仙侠、都市、历史、奇幻、科幻（网文风格）
- 特点：有金手指、升级系统、爽点设计

### 文学类
- 纯文学、推理悬疑、言情文学、科幻文学
- 特点：注重人物深度、文学性、思想性，无金手指

### 短剧类
- 逆袭爽剧、甜宠、虐恋、复仇、穿越重生、都市情感、古装
- 特点：强反转、快节奏、情绪冲击、每集结尾有悬念钩子
- 格式：【场景】、（动作）、角色名：台词、「旁白」

## 开发

```bash
# 安装开发依赖
pip install -e ".[dev]"

# 运行测试
pytest

# 代码检查
python -m py_compile aznovel/app.py
```

## License

MIT
