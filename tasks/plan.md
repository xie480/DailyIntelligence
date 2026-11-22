# Daily Intelligence v1.0 实施计划

## 目标

在 `E:\YilenaCode\DailyIntelligence` 交付一套仅依赖 Python 标准库的轻量技术情报系统。代码与 `E:\HermesData\daily-intelligence` 运行数据分离，Hermes 只通过 Skills、CLI 和 Cron 使用本项目，不直接修改 Hermes 当前运行环境。

## 依赖关系

```text
配置与路径
    ↓
SQLite 数据库与数据模型
    ↓
URL/内容去重
    ↓
GitHub / RSS 采集器
    ↓
兴趣画像与推荐排序
    ↓
日报渲染与 CLI
    ↓
Hermes Skills、Cron 与部署文档
```

## 分阶段任务与验收标准

### 阶段 0：基线

- 初始化本地 Git，建立 `.gitignore`。
- 固化 Python、Hermes 版本和目录边界。
- 写入本计划和任务清单。

### 阶段 1：基础设施

- 提供运行路径配置、数据模型和 SQLite 迁移。
- 支持事务、幂等写入、运行记录和历史推荐查询。
- 使用临时目录完成数据库回归测试。

### 阶段 2：采集与去重

- 提供 GitHub API 客户端、RSS/Atom 解析器和失败重试。
- 实现 URL 规范化、内容指纹、相似度和同仓库识别。
- 外部请求全部可替换为 Mock，不在测试中访问真实服务。

### 阶段 3：画像、推荐与日报

- 支持 JSON 画像持久化、显式反馈、隐式信号、查看/关闭/重置。
- 支持历史推荐去重、兴趣匹配排序、日报 Markdown 生成。
- 覆盖日期、时区、重复执行保护和失败恢复。

### 阶段 4：CLI、Skills 与部署

- 提供 `python -m daily_intelligence` 的初始化、采集、推荐、反馈、画像、日报和 dry-run 命令。
- 创建 `daily-intelligence-local`、`github-radar`、`tech-news-radar`、`interest-profile` 四个完整 Skills。
- 编写 README、CHANGELOG、架构说明和 `deployment/HERMES_INSTALL.md`。

### 阶段 5：收口

- 在 Windows 当前环境运行完整 `unittest` 套件和 CLI 冒烟命令。
- 检查 Git diff、敏感信息、文档路径和未验证边界。
- 形成最终本地提交并输出交付报告。

## 风险与边界

- GitHub API、RSS 站点、Hermes Web Search 和真实 QQ Bot 运行流不在离线测试范围内。
- 不修改 `E:\HermesData` 中的 Hermes 配置、Skills 或 Cron；安装步骤只写入文档。
- 不伪造 Star 增长、新闻发布时间、QQ 消息上下文或生产成功结果。

---

# 创作者动态增量改造计划（2026-11-22）

## 目标

在不改变原有 GitHub/RSS 采集、日报时间和 Hermes QQ Bot 链路的前提下，增加 Bilibili 视频、Bilibili 动态和 YouTube 视频的按日报时间窗口采集、账号管理、幂等持久化与日报章节整合。

## 阶段与验收

### 阶段 1：审计与数据基础

- [x] 完成现有入口、调用链、数据库、报告和 Hermes 边界审计。
- [x] 记录增量方案、风险和验证边界。
- [x] 新增 SQLite v2 创作者表、时间窗口和账号管理模型。

### 阶段 2：账号管理与链接解析

- [x] 解析 Bilibili UID、YouTube Channel ID 和 `@handle`。
- [x] 实现授权账号的添加、查看、删除、暂停、恢复和监控类型配置。
- [x] 添加 CLI/Skill 自然语言路由说明。

### 阶段 3：平台采集

- [x] 实现 Bilibili 投稿分页、动态游标、卡片分类和 BV/Dynamic ID 去重。
- [x] 实现 YouTube Atom Feed、频道页面解析和 Video ID 去重。
- [x] 完成有限重试、失败隔离和不推进检查点。

### 阶段 4：日报整合与可靠性

- [x] 在现有日报增加创作者动态章节和来源状态。
- [x] 报告成功后推进检查点，失败时保留窗口并支持重试。
- [x] 更新 README、部署说明和 CHANGELOG。

### 阶段 5：测试与收口

- [x] 新增时间窗口、链接解析、采集 Fixture、持久化和报告集成测试。
- [x] 运行全量 unittest、compileall、CLI dry-run 和隔离目录 smoke。
- [x] 检查分阶段 Git 提交、敏感信息和未验证边界。

## 阶段性提交约定

每个阶段先运行聚焦测试，再运行受影响的全量测试并提交本地 Git；提交消息遵循 `类型：中文描述`，不 Push，不修改 Hermes 运行数据。

---

# Hermes `dailyintelligence-creators` Skill 开发计划（2026-11-22）

## 目标

在现有创作者账号服务和 CLI 之上增加一个可交给 Hermes 安装的独立 Skill。Skill 只负责通过受信任的 Hermes 私聊 sender 身份路由账号管理，不复制采集逻辑、不直接访问 SQLite，也不修改 Hermes 运行目录、Profile 或 Gateway。

## 现状与关键决策

- 复用 `python -m daily_intelligence creator ...` 和 `CreatorAccountService`，不新增第二套账号业务逻辑。
- 为创作者 CLI 增加显式 `--json` 机器接口；保留无 `--json` 的既有人类可读输出，避免无必要的兼容性破坏。
- Skill 使用 `list` 结果按名称或主页链接解析目标；零匹配或多匹配时先询问用户，多匹配不执行变更；删除始终要求确认。
- 数据目录和 owner key 由 Hermes 可信运行上下文提供，Skill 不硬编码数据库路径、不接受用户文本中的 owner key。
- 使用现有 Hermes Skill frontmatter 结构；命令细节放入 `references/commands.md`，避免在 `SKILL.md` 中重复协议。

## 阶段与验收

### 阶段 0：审计、计划和基线

- [x] 阅读项目规范、已有 Skill 示例、账号管理调用链、数据库模型和测试框架。
- [x] 运行现有 `unittest` 与 `compileall`，记录基线。

### 阶段 1：结构化 Backend CLI 契约

- [ ] 先补充 CLI `--json` 成功、重复、未授权、删除、暂停、恢复和配置用例，并确认新增用例按预期失败。
- [ ] 复用现有 service 实现结构化 JSON 成功/失败输出和稳定错误码；不直接操作数据库。
- [ ] 运行聚焦 CLI/creator 测试、全量 unittest 和 compileall，提交 `feat：提供创作者管理 CLI 结构化接口`。

### 阶段 2：Hermes Skill 源文件

- [ ] 新增 `skills/dailyintelligence-creators/SKILL.md` 与 `references/commands.md`。
- [ ] 明确平台识别、重复处理、列表分组、删除确认、暂停/恢复、监控类型、权限和禁止事项。
- [ ] 添加 Skill frontmatter/命令一致性静态测试，提交 `feat：新增 DailyIntelligence 创作者 Hermes Skill`。

### 阶段 3：项目文档与收口

- [ ] 更新 README、Hermes 安装说明和现有总入口 Skill 的职责边界，保留“只开发不安装”限制。
- [ ] 新增本次技术留痕文档，区分已验证的本地 CLI/测试与未验证的 Hermes 真实安装、QQ 入站和平台网络。
- [ ] 运行完整测试、compileall、隔离数据库 smoke 和 Skill 静态检查，提交 `docs：补充创作者 Skill 安装交接说明`。

## 风险与待验证项

| 风险 | 处理方式 |
| --- | --- |
| Hermes 版本的 terminal 参数接口可能变化 | Skill 只引用已确认的 `terminal` 工具概念和仓库已有 frontmatter；安装时按目标版本 help 校验 |
| YouTube handle/Bilibili 名称解析依赖真实网络 | 本地测试使用 Fake opener；真实平台解析标记为部署后验证 |
| 首次 owner 自动登记可能被误用 | Skill 必须从 Hermes 入站上下文注入稳定 sender ID；预置白名单由 Backend 校验，用户文本不能覆盖 |
| 删除/暂停按名称可能多匹配 | Skill 先 list，再要求选择/确认，最终 CLI 只接受精确平台和 account key |

