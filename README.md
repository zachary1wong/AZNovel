# AZNovel

AI辅助中文小说写作CLI工具。支持网文、文学和短剧剧本三类题材，通过对话式交互完成创作全流程。

## 功能特点

- **多题材支持**：
  - 网文：玄幻/仙侠/都市/历史/奇幻/科幻
  - 文学：纯文学/推理悬疑/言情文学/科幻文学
  - 短剧：逆袭爽剧/甜宠/虐恋/复仇/穿越重生/都市情感/古装
- **6步写作流水线**：预检 → 契约刷新 → 上下文组装 → 初稿生成 → 审查 → 提交
- **对话式初始化**：AI引导用户构思设定、生成大纲
- **自然语言操作**：用对话方式驱动写作、审查、重写等操作
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
2. 设定主角信息
3. 规划写作规模（总字数、每章字数）
4. 生成大纲
5. 创建项目结构

### 3. 写作章节

```bash
# 写第1章
aznovel write --chapter 1

# 快速模式（跳过审查）
aznovel write --chapter 2 --mode fast

# 最小模式（仅格式检查）
aznovel write --chapter 3 --mode minimal
```

### 4. 对话模式

进入AI对话模式，用自然语言操作：

```bash
aznovel chat
```

对话示例：
```
你 > 写下一章
你 > 审查第3章
你 > 显示项目状态
你 > 重写第2章，把开头改得更吸引人
```

### 5. 无参数启动

```bash
# 在项目目录内：自动进入对话模式
aznovel

# 在非项目目录：自动进入初始化流程
aznovel
```

## 命令说明

### init - 初始化项目

```bash
# 对话式初始化
aznovel init

# 直接指定参数
aznovel init --title "我的小说" --genre 都市 --protagonist 张三

# 在指定目录初始化
aznovel init ./my-project
```

### write - 写作章节

```bash
aznovel write --chapter <章节号> [--mode default|fast|minimal] [--profile <配置名>]
```

模式说明：
- `default`：完整流水线（初稿→审查→润色→再审查）
- `fast`：快速模式（初稿→轻量审查）
- `minimal`：最小模式（仅格式检查）

### review - 审查章节

```bash
aznovel review --chapter <章节号> [--dims 维度1,维度2]
```

审查维度：consistency, timeline, characterization, plot, style, ai_flavor

### rewrite - 重写章节

```bash
aznovel rewrite --chapter <章节号> --modification "修改要求" [--cascade]
```

如果修改影响后续章节，会提示删除后续章节。使用 `--cascade` 强制删除。

### chat - 对话模式

```bash
aznovel chat [--fast] [--profile <配置名>]
```

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
aznovel config set api_key YOUR_KEY --global

# 查看已保存的LLM配置
aznovel config profiles
```

## LLM配置管理

支持保存多个LLM配置，方便切换：

```bash
# 查看已保存配置
aznovel config profiles

# 使用指定配置
aznovel write --chapter 1 --profile gpt4o
aznovel chat --profile claude
```

## 并发使用

支持多个session同时运行不同项目：

```bash
# 终端1：用配置A写小说1
cd novel-1
aznovel write --chapter 1 --profile config-a

# 终端2：用配置B写小说2
cd novel-2
aznovel write --chapter 1 --profile config-b
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
