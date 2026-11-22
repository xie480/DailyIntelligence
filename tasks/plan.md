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
- [ ] 新增 SQLite v2 创作者表、时间窗口和账号管理模型。

### 阶段 2：账号管理与链接解析

- [ ] 解析 Bilibili UID、YouTube Channel ID 和 `@handle`。
- [ ] 实现授权账号的添加、查看、删除、暂停、恢复和监控类型配置。
- [ ] 添加 CLI/Skill 自然语言路由说明。

### 阶段 3：平台采集

- [ ] 实现 Bilibili 投稿分页、动态游标、卡片分类和 BV/Dynamic ID 去重。
- [ ] 实现 YouTube Atom Feed、频道页面解析和 Video ID 去重。
- [ ] 完成有限重试、失败隔离和不推进检查点。

### 阶段 4：日报整合与可靠性

- [ ] 在现有日报增加创作者动态章节和来源状态。
- [ ] 报告成功后推进检查点，失败时保留窗口并支持重试。
- [ ] 更新 README、部署说明和 CHANGELOG。

### 阶段 5：测试与收口

- [ ] 新增时间窗口、链接解析、采集 Fixture、持久化和报告集成测试。
- [ ] 运行全量 unittest、compileall、CLI dry-run 和隔离目录 smoke。
- [ ] 检查分阶段 Git 提交、敏感信息和未验证边界。

## 阶段性提交约定

每个阶段先运行聚焦测试，再运行受影响的全量测试并提交本地 Git；提交消息遵循 `类型：中文描述`，不 Push，不修改 Hermes 运行数据。

