# Changelog

## [创作者动态增量改造] - 2026-11-22

### Added

- SQLite v2 创作者账号、授权 owner、事件、来源运行和独立检查点表，沿用原有数据库和事务。
- Bilibili 投稿分页、WBI 签名、空间动态游标、文字/图片/转发/专栏分类和 BV/Dynamic ID 去重。
- YouTube 公开 Atom Feed、`/channel/UC...`、`/@handle` 与旧式频道页解析，不依赖 Data API Key。
- `creator add/list/pause/resume/configure/remove` CLI 与 `daily-intelligence-local` Skill 的自然语言管理路由。
- 日报“创作者动态追踪”章节、QQ Markdown 同步渲染、失败状态和报告成功后检查点推进。

### Verification boundary

- 创作者 URL、时间窗口、分页/Feed Fixture、失败隔离、幂等事件、CLI 和日报整合使用本地 unittest 验证。
- 真实 Bilibili 接口、Cookie 风控、YouTube 频道页、Hermes Cron、QQ 入站和实际消息投递仍需目标环境单独验收。

## [第三轮升级] - 2026-11-22

### Added

- GitHub 最终候选 README Base64 解析、长度限制、项目元数据和结构化 `project_analysis` 交接。
- Hermes `web_search`/`web_extract` 的 schema 1.0 JSON 交接、原子写入、状态校验和 `import-handoff` CLI。
- 专业分区日报、QQ Markdown 阅读版、消息边界拆分、采集状态和轻量质量指标。
- 主动查询 `query` CLI、结构化查询信号、“不感兴趣/想深入了解”反馈，以及高重要性内容探索位。
- 四个 Hermes Skill、README、部署说明和示例交接路径更新。

### Verification boundary

- 本地 unittest、compileall、CLI 版本/帮助和 dry-run 属于自动化/离线验证。
- Hermes Cron、真实 Web Search、真实 GitHub/RSS 网络、QQ 入站/主动推送和图片/文件媒体上传仍需目标环境单独验收。

## [1.0.0] - 2026-11-21

### Added

- 提供 Python 标准库实现的 SQLite、GitHub、RSS/Atom、去重、画像、推荐和日报模块。
- 提供 python -m daily_intelligence CLI，覆盖初始化、采集、推荐、反馈、画像、日报和 dry-run。
- 提供 daily-intelligence-local、github-radar、tech-news-radar、interest-profile 四个 Hermes Skills；本地调度 Skill 与 Hermes Hub 同名项隔离。
- 提供采集源模板、用户画像模板、架构说明和 Hermes 安装/回滚说明。
- 支持项目级 `GITHUB_PROXY`，独立控制 GitHub API 的 HTTP/HTTPS 代理连接。
- 使用 unittest 覆盖 URL、指纹、相似度、仓库识别、Star 增长、历史去重、反馈、画像、日报、CLI 和运行保护。

### Known limitations

- 本版本没有修改或安装到 Hermes 当前运行环境。
- 真实 GitHub API、RSS 站点、Hermes Web Search、QQ Bot 被动回复和 Cron 实际触发未在离线测试中验证。
- GitHub Trending 页面没有稳定官方 API；默认采集使用 GitHub 官方 Search API，Trending 页面作为 Hermes Web Search 的补充输入。

