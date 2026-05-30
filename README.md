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
- **自然语言操作**：用对话方式驱动写作、审查、重写、精修等操作（支持14种操作）
- **章节精修**：逐段润色文字，修复语病和不通顺，不改剧情结构；支持单章/范围/全部精修
- **反推大纲**：从已写章节反推大纲，方便检阅整本书结构
- **需求驱动大纲生成**：可指定创作需求，AI严格按需求设计大纲
- **章节重写**：支持修改已有内容，自动检测是否影响后续章节
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

### 5. 对话模式

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
你 > 生成大纲，加入一个反派角色
你 > 修改大纲，第3章要加入一场战斗
你 > 更新设定，主角境界提升到筑基
```

对话模式支持14种操作：
| 操作 | 说明 |
|------|------|
| `write_next` | 写下一章 |
| `write_chapter` | 写指定章节 |
| `write_batch` | 连续写多章 |
| `review_chapter` | 审查指定章节 |
| `review_latest` | 审查最新一章 |
| `show_status` | 显示项目状态 |
| `show_chapter` | 查看章节内容 |
| `update_setting` | 更新设定文件 |
| `generate_outline` | 重新生成大纲 |
| `revise_outline` | 修改大纲 |
| `show_outline` | 显示当前大纲 |
| `rewrite_chapter` | 重写章节 |
| `reverse_outline` | 反推大纲 |
| `polish_chapter` | 精修章节 |

### 6. 反推大纲

从已写章节反向生成大纲，不覆盖原大纲：

```bash
aznovel reverse-outline
```

### 7. 需求驱动大纲生成

在对话模式中，可以指定创作需求让AI严格按需求生成大纲：

```
你 > 生成大纲，加入一个反派角色
你 > 修改大纲，第3章要加入一场战斗
你 > 重新生成大纲，要求：主角在第5章获得新能力
```

AI会将用户需求标记为最高优先级，大纲的每一卷都有完整的逐章明细。

### 8. 无参数启动

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
