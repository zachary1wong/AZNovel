# AZNovel 开发进度

## 已完成

### 1. 精修功能（Polish）
- [x] `aznovel/cli/polish_cmd.py` — 批量/逐段精修，支持 `--careful` 模式
- [x] `aznovel/app.py` — `polish` CLI 命令（`-c`, `-s/-e`, `--all`, `--careful`）
- [x] `aznovel/cli/chat_cmd.py` — `polish_chapter` 对话动作（action #14）
- [x] 修复 LLMResponse.strip() bug
- [x] 修复 "无修改" 被当成修改内容保存的解析 bug
- [x] 修复 LLM 注释（注：...）被保存的 bug
- [x] 添加假修改过滤（对比原文和返回内容）
- [x] 批量模式自动保存（`--all` 和范围模式不弹确认）

### 2. 大纲遵循修复（代码已改，未验证）
- [x] `aznovel/models/contract.py` — ChapterBrief 增加 `summary` 字段
- [x] `aznovel/core/contract_manager.py` — 提取 `outline["summary"]`，填充 `must_cover`
- [x] `aznovel/core/context.py` — `_build_story_context` 中新增"本章剧情大纲"section，标记为必须遵循
- [x] `aznovel/core/pipeline.py` — 系统 prompt 第1条改为"必须严格按照本章剧情大纲写作"，精简重复的反AI规则

## 未完成

### 1. 验证大纲遵循修复
- [ ] 删除第3章及以后章节（第3-33章已删除，但第10-33章还残留，需要彻底清理）
- [ ] 清理 `.aznovel/commits/` 和 `.aznovel/contracts/` 中对应的缓存文件
- [ ] tmux 测试 `aznovel write -c 3` 重写第3章
- [ ] 确认新第3章包含：陈琪出场、听力障碍、与张茜茜冲突
- [ ] 验证通过后继续写第4章及后续

### 2. 残留文件清理
- [ ] 第10-33章正文文件还在（之前删除命令的 glob 没匹配到两位数章号）
- [ ] 对应的 commit 和 contract 缓存也需要清理

## 关键文件路径
- 项目目录：`/Users/wangzesen/Documents/Projects/Novels/听不见的炮声/`
- 大纲：`大纲/outline.json`
- 正文：`正文/第XXX章.md`
- tmux session：`NovelTBJDPS`

## 大纲第3章内容（用于验证）
```json
{
  "chapter": 3,
  "title": "失聪的维修工",
  "goal": "引入陈琪，展现其反派特质",
  "summary": "设备机械厂的高级技术员陈琪因听力障碍在维修时与张茜茜发生冲突，他行为冷漠、城府深沉，让张茜茜极为反感。"
}
```
