# Changelog

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

