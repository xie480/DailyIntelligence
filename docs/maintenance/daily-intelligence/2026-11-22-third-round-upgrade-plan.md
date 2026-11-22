# Daily Intelligence 第三轮升级实施方案

## 目标

在保留 Python 标准库、SQLite、项目级 GitHub 代理和四个 Hermes Skill 的前提下，补齐 GitHub 项目深度采集、Hermes 原生联网搜索交接、新闻跨来源去重、专业日报和 QQ Markdown 阅读版。所有外部搜索与 QQ 投递能力都必须区分“代码已实现”“Mock/离线验证”和“需要 Hermes 运行环境验证”。

## 约束

- 不修改 `.env` 中的 `GITHUB_TOKEN`、`GITHUB_PROXY`。
- 不修改 Hermes Gateway、Windows Scheduled Task、Hermes 外部配置或真实 QQ 消息。
- 不删除 SQLite、历史日报或用户兴趣数据。
- 不增加付费 API、HTTP 服务、队列、Redis、PostgreSQL 或 Docker。
- 新能力优先使用现有 `metadata_json`，保持 SQLite v1 数据兼容。
- 测试全部使用 Fake/Mock，真实网络和 QQ 投递单独标记为未验证。

## 方案取舍

1. Python 直接接第三方搜索 API：依赖新的凭证和服务，违反 Hermes 工具边界，放弃。
2. Hermes 直接拼最终 Markdown：难以复用 Python 的去重、推荐、统计和原子落盘，放弃。
3. Hermes 原生 `web_search` / `web_extract` 生成结构化 JSON，Python 校验、融合、持久化和渲染：依赖少、可测试、能明确记录失败状态，采用。

## 阶段拆分

### 阶段 0：方案与基线

- 固化本方案、当前 Hermes 工具事实和外部阻塞点。
- 检查工作区与历史提交格式。

### 阶段 1：GitHub 深度采集

- 增加 README API 获取、Base64 解码、长度限制和失败状态。
- 补齐 homepage、watchers、topics、license、创建/更新/推送和 Release 时间等元数据。
- 仅对最终选出的有限项目读取 README。
- 支持 Hermes 导入的项目分析摘要、特色、场景、推荐理由和证据链接。

### 阶段 2：Hermes Web Search 交接与新闻融合

- 增加版本化 JSON 交接格式、原子写入/读取和字段校验。
- 覆盖 AI、Agent、软件开发三个领域，每个领域支持多条查询与独立失败状态。
- 将 Web Search 新闻与 RSS 合并，按规范化 URL、指纹、标题相似度和官方来源优先去重。
- 提供 CLI 导入命令，并记录 `web_search` 运行状态。

### 阶段 3：日报与 QQ 阅读版

- 将日报改为摘要、项目卡片、新闻条目、今日推荐和采集状态结构。
- 增加 QQ Markdown 版、完整条目边界拆分、序号和链接保留。
- 提供 Markdown 附件准备能力；不在项目内实现 QQ 媒体上传或主动发送 Adapter。

### 阶段 4：推荐、Skills 与交付文档

- 将重要性、可信度、时效、探索位和负反馈纳入推荐评分。
- 更新四个 Skills、README、架构和 Hermes 部署说明。
- 生成 Mock 日报预览并记录测试、compileall、CLI 和 diff 检查结果。

## 验收标准

- 旧有测试不删除且全量通过。
- 新增测试覆盖 README 解析、Release/时间字段、JSON 校验、搜索失败隔离、跨来源去重、日报和 QQ 拆分。
- `compileall`、`--version`、`--help`、`dry-run`、`git diff --check` 均有实际结果。
- 报告明确列出真实 GitHub、Hermes Cron、QQ Markdown/媒体和主动推送的未验证或阻塞范围。

