# Daily Intelligence

Daily Intelligence 是一个面向 Hermes Agent 的轻量个人技术情报系统。第三轮升级后，它使用 Python 标准库、SQLite、JSON 和 Markdown，代码与运行数据分离，不增加常驻服务、Web Dashboard 或额外机器人。

## 目标与边界

- 采集 GitHub AI/Agent/MCP/开发工具项目，以及 RSS/Atom 技术新闻。
- 默认使用 GitHub 官方 Search API，并提供 Trending HTML 补充解析入口。
- 通过 URL、内容指纹和标准库文本相似度做三层去重。
- 通过 JSON 画像和 SQLite 反馈历史进行可解释推荐。
- 生成 YYYY-MM-DD.md 日报，供 Hermes Skill 或用户主动查询。
- 在日报生成时按固定时间窗口采集 Bilibili UP 主视频、动态和 YouTube 频道视频。
- 通过授权 owner 的 CLI/Skill 管理创作者账号；不运行常驻 CreatorRadar 进程。
- 由 Hermes 原生 `web_search`/`web_extract` 搜索并核实 AI、Agent、软件开发新闻，通过 `config/hermes-handoff.json` 与 Python 交接。
- 获取最终 GitHub 候选项目 README，保存结构化项目分析、证据链接和完整元数据。
- 生成完整 Markdown、QQ Markdown 阅读版和按项目/新闻边界拆分的消息片段。
- 记录用户主动查询、喜欢、不感兴趣、收藏和深入了解等结构化反馈，并保留重要内容的跨领域探索位。
- QQ Bot 继续使用 Hermes 已有的消息路由；本项目不创建 Adapter、不伪造消息、不主动绕过平台限制。
- 不扫描其他用户聊天记录，只保存结构化兴趣信号和短依据。

## 目录

~~~~text
DailyIntelligence/
├── daily_intelligence/
│   ├── collectors/
│   │   ├── github.py
│   │   ├── rss.py
│   │   └── creators.py
│   ├── creator_service.py
│   ├── creator_urls.py
│   ├── cli.py
│   ├── config.py
│   ├── database.py
│   ├── deduplication.py
│   ├── handoff.py
│   ├── models.py
│   ├── profile.py
│   ├── recommendations.py
│   └── report.py
├── skills/
├── tests/
├── config/
├── deployment/
├── docs/
├── .env.example
├── README.md
└── CHANGELOG.md
~~~~

## 快速开始

默认运行数据目录是 E:\HermesData\daily-intelligence。也可以为测试或多套 Hermes Profile 指定其他目录。

~~~~powershell
python -m daily_intelligence --data-dir "E:\HermesData\daily-intelligence" init-db
python -m daily_intelligence --data-dir "E:\HermesData\daily-intelligence" collect-github
python -m daily_intelligence --data-dir "E:\HermesData\daily-intelligence" collect-rss
python -m daily_intelligence --data-dir "E:\HermesData\daily-intelligence" import-handoff --file "E:\HermesData\daily-intelligence\config\hermes-handoff.json"
python -m daily_intelligence --data-dir "E:\HermesData\daily-intelligence" report
~~~~

`report` 会在任务启动时固定创作者采集截止时间，并在原有日报中追加“创作者动态追踪”章节。没有监控账号时只显示未配置状态。

只查看推荐，不写推荐历史：

~~~~powershell
python -m daily_intelligence --data-dir "E:\HermesData\daily-intelligence" recommend --no-record
python -m daily_intelligence --data-dir "E:\HermesData\daily-intelligence" query "MCP"
~~~~

离线检查日报渲染，不访问网络或写运行数据：

~~~~powershell
python -m daily_intelligence --data-dir "$env:TEMP\daily-intelligence-manual" dry-run
~~~~

## CLI 命令

| 命令 | 作用 |
| --- | --- |
| init-db | 创建 SQLite、画像 JSON、目录和默认 sources.json |
| collect-github | 使用 GitHub 官方 Search API，保存项目和每日 Star 快照 |
| collect-rss | 读取 RSS/Atom，保留 24 小时主体和 7 天补充窗口 |
| import-handoff --file PATH | 校验并导入 Hermes `web_search`/`web_extract` 结果 |
| recommend | 获取待推荐内容，支持 --type、--limit、--json |
| feedback TEXT | 解析明确反馈，可用 --target 指定项目 |
| query TOPIC | 记录一次主动查询主题，三次重复查询后小幅增加权重 |
| profile show/reset/enable/disable | 查看或管理画像 |
| report | 按推荐结果保存 Markdown 日报，支持 --date YYYY-MM-DD |
| creator add URL... | 添加一个或多个 Bilibili/YouTube 监控账号 |
| creator list | 查看当前 owner 的监控账号 |
| creator pause/resume PLATFORM KEY | 暂停或恢复账号 |
| creator configure PLATFORM KEY | 修改视频/动态监控类型 |
| creator remove PLATFORM KEY | 删除账号及其创作者事件 |
| dry-run | 使用固定样例渲染日报，不建立运行数据 |

全局参数必须放在子命令前：

~~~~powershell
python -m daily_intelligence --data-dir "E:\HermesData\daily-intelligence" --timezone "Asia/Shanghai" report
~~~~

创作者管理命令由 Hermes 传入当前私聊的真实 sender ID。没有预置授权时，首次创作者管理请求会自动登记该 sender ID；后续请求必须使用同一个 ID：

~~~~powershell
python -m daily_intelligence --data-dir "E:\HermesData\daily-intelligence" creator add --owner-key "qq:user-123" "https://space.bilibili.com/123456"
python -m daily_intelligence --data-dir "E:\HermesData\daily-intelligence" creator add --owner-key "qq:user-123" "https://www.youtube.com/@example"
python -m daily_intelligence --data-dir "E:\HermesData\daily-intelligence" creator list --owner-key "qq:user-123"
python -m daily_intelligence --data-dir "E:\HermesData\daily-intelligence" creator pause bilibili 123456 --owner-key "qq:user-123"
~~~~

Bilibili 默认开启视频和动态监控，YouTube 只开启视频监控；直播、YouTube 社区帖子和 Bilibili 直播不会被采集。`@handle` 与旧式 YouTube 频道链接会先解析真实 Channel ID，解析失败时不会写入错误账号。

## 配置与运行数据

代码目录固定为 E:\YilenaCode\DailyIntelligence，运行数据默认位于 E:\HermesData\daily-intelligence：

- database/intelligence.db：SQLite 数据库。
- config/user_profile.json：当前用户画像。
- config/sources.json：实际采集源；可由 config/sources.example.json 初始化。
- reports/YYYY-MM-DD.md：每日日报。
- reports/YYYY-MM-DD.qq.md：供 QQ Bot 适配器上传或发送前预览的 Markdown 附件。
- config/hermes-handoff.json：最近一次通过 schema 校验的 Hermes 搜索/项目分析交接。
- logs/daily-intelligence.log：CLI 运行日志。

GitHub Token 是可选的。项目根目录的 `.env` 用作本项目独立的凭证入口，实际值由本机用户填写。`.env` 已被 Git 忽略，不要把真实 Token 发到聊天窗口或写入源码、JSON 模板、日报和日志。当前进程已有的 `GITHUB_TOKEN` 优先于项目 `.env`；两处都没有 Token 时继续使用公开 API，并提示配额较低。

GitHub 专用代理使用 `GITHUB_PROXY` 配置，优先级为进程级 `GITHUB_PROXY`、项目 `.env` 中的 `GITHUB_PROXY`、Python 自动代理发现。显式代理会同时用于 GitHub API 的 HTTP/HTTPS 请求，并覆盖 `HTTP_PROXY`、`HTTPS_PROXY` 和 `ALL_PROXY`；显式配置无效或与 `NO_PROXY` 冲突时直接报错，不会静默直连。`.env.example` 使用 `http://127.0.0.1:7890` 作为示例地址，需按本机代理客户端实际监听地址调整。

创作者管理默认不需要配置授权环境变量：首次私聊的真实 sender ID 会写入 SQLite 授权表并成为首个 owner。`CREATOR_ADMIN_KEYS` 是可选的预置/多管理员白名单，多个值用逗号或分号分隔；`CREATOR_OWNER_KEY` 仅用于本地 CLI 省略参数，Hermes 应优先传入当前私聊 sender ID。Bilibili 动态接口需要 Cookie 时在本机 `.env` 设置 `BILIBILI_COOKIE`，该值只在内存中用于请求，不写入 SQLite、日志、日报或 Git。

配置模块根据源码位置解析项目根目录，不依赖当前工作目录、Hermes Gateway 环境继承或 GitHub CLI。GitHub API 的 Token 只在进程运行时由统一配置模块读取，请求固定使用 `https://api.github.com`、`Accept: application/vnd.github+json`、`X-GitHub-Api-Version: 2022-11-28` 和 `User-Agent: DailyIntelligence`；Token 只放在 `Authorization: Bearer ...` 请求头中，不进入 URL、数据库或缓存。客户端拒绝非 HTTPS、非 `api.github.com` 地址和重定向，并把错误中的 Token 清理后再交给 CLI。401 会提示 Token 无效或已过期，403/429 按限流响应头和有限指数退避处理。

限流和暂时性网络错误最多重试 2 次，单次等待上限为 30 秒；数值或 HTTP-date `Retry-After`、`X-RateLimit-Reset` 会被尊重，超过上限时立即返回脱敏错误。ETag 和响应体只保存在当前 `GitHubClient` 实例的有限内存缓存中，不写入运行数据目录。

## 测试

项目没有第三方运行时依赖，使用 Python unittest：

~~~~powershell
python -m unittest discover -s tests -v
~~~~

当前测试使用 Fake opener，不向真实 GitHub、RSS、QQ Bot 或 Hermes 发送请求。

## Hermes 使用方式

将 `E:\YilenaCode\DailyIntelligence\skills\daily-intelligence-local` 及其他三个 Skill 作为 Hermes 外部只读 Skills 目录，或按 deployment/HERMES_INSTALL.md 复制到目标 Profile 的 Skills 目录。完整日报流程由 `daily-intelligence-local` 编排：先运行 GitHub/RSS 采集，再让 Hermes 用 `web_search` 覆盖三个新闻领域、用 `web_extract` 核实原文，写入交接 JSON，执行 `import-handoff` 后运行 `report`。`report` 会在同一任务内按账号和内容类型采集创作者更新，最后生成完整和 QQ Markdown 日报。QQ Bot 用户主动提问或管理账号时由同一 Skill 读取日报、数据库和画像后被动回复。

当前仓库只负责生成本地报告、QQ Markdown 和附件文件，不包含 QQ 适配器或媒体上传实现。Cron 使用 `local` 投递时不能自动推断 QQ 私聊目标；真实主动推送、图片/文件上传和消息限额需要 Hermes 运行环境、官方 API 和用户授权单独验收。

完整模块边界、数据流和未验证项见 docs/architecture.md。

## Git 交付

开发过程按逻辑阶段形成了本地提交，提交消息使用 `类型：中文描述` 格式；本轮只提交到本地 `main`，未执行 Push。真实 API、Hermes Cron 和 QQ 投递状态见 `deployment/HERMES_INSTALL.md` 与 `docs/maintenance/daily-intelligence/`。

