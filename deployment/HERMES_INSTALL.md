# Hermes 安装与回滚说明

本文只描述安装方法，不在交付过程中直接修改 Hermes 当前运行环境。

## 1. 路径约定

| 内容 | 路径 |
| --- | --- |
| 项目代码 | E:\YilenaCode\DailyIntelligence |
| 运行数据 | E:\HermesData\daily-intelligence |
| SQLite | E:\HermesData\daily-intelligence\database\intelligence.db |
| 用户画像 | E:\HermesData\daily-intelligence\config\user_profile.json |
| 日报 | E:\HermesData\daily-intelligence\reports\YYYY-MM-DD.md |
| Hermes 交接 | E:\HermesData\daily-intelligence\config\hermes-handoff.json |
| QQ 阅读版 | E:\HermesData\daily-intelligence\reports\YYYY-MM-DD.qq.md |
| Skills 源目录 | E:\YilenaCode\DailyIntelligence\skills |

代码与运行数据必须保持分离。不要把数据库、Token、日报或日志提交回 Git 仓库。

## 2. 安装前检查

本次只读勘察得到：

- Windows 当前 Python 3.13.7。
- Hermes 源码版本 v0.23.0。
- Hermes Home 为 E:\HermesData。
- Hermes 配置示例支持 skills.external_dirs，并将外部目录作为只读 Skills 源。
- Hermes 的 qqbot 工具集已经存在，当前项目不需要新增消息 Adapter。
- Daily Intelligence 的 SQLite schema 已增量升级到 v2，创作者账号、事件和检查点仍保存在同一个 `intelligence.db`。
- Hermes 当前可用的原生联网工具名称已从只读 Profile/请求转储确认是 `web_search` 和 `web_extract`；Python 不直接调用这两个 Agent 工具。
- 当前只读检查到的 Hermes Cron 配置没有 Daily Intelligence Report 任务，不能把旧配置或用户任务描述当作当前已生效状态。

部署机器应再次检查版本和路径，不要假定未来版本的配置字段完全一致。

~~~~powershell
python --version
hermes --version
Get-ChildItem "E:\HermesData"
~~~~

## 3. 初始化运行目录

在项目目录执行：

~~~~powershell
Set-Location "E:\YilenaCode\DailyIntelligence"
python -m daily_intelligence --data-dir "E:\HermesData\daily-intelligence" init-db
~~~~

该命令只创建 Daily Intelligence 自己的目录、SQLite、画像 JSON 和 sources.json，不修改 Hermes 配置。

如需自定义采集源，可复制 config/sources.example.json 到运行目录的 config/sources.json 后编辑 URL、分类和查询。GitHub Token 由 Daily Intelligence 项目根目录的 `.env` 独立读取：

~~~~powershell
Set-Location "E:\YilenaCode\DailyIntelligence"
if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
}
# 仅在本机编辑 .env 中的 GITHUB_TOKEN=，不要把真实值写入命令历史。
~~~~

项目当前进程中的 `GITHUB_TOKEN` 仍优先于 `.env`；没有 Token 时使用匿名公开 API。不要把真实 Token 写入 PowerShell 历史、sources.json、日报或日志。Hermes 只负责调度，不需要向 Python 子进程传递 Token。

GitHub API 专用代理通过项目 `.env` 的 `GITHUB_PROXY` 配置，例如 `GITHUB_PROXY=http://127.0.0.1:7890`。进程级 `GITHUB_PROXY` 优先于项目文件；未配置时才使用 Python 自动代理发现。该配置只作用于 GitHubClient，不会修改 Hermes、Windows 系统代理或 RSS 客户端。显式代理不可用或被 `NO_PROXY` 绕过时，命令会明确失败。

创作者账号管理可以直接使用首次私聊自动登记的 sender ID；只有需要预置或配置多个管理员时，才在项目 `.env` 中填写授权白名单：

~~~~dotenv
# 可选：预置或追加多个稳定 sender ID，逗号分隔
CREATOR_ADMIN_KEYS=
# 可选：本地 CLI 省略 --owner-key 时使用；Hermes 应传入当前私聊 sender ID
CREATOR_OWNER_KEY=
# Bilibili 动态接口需要时再填写，不能提交真实 Cookie
BILIBILI_COOKIE=
~~~~

首次创作者管理请求会把 Hermes 传入的当前私聊 sender ID 原子写入 SQLite；之后其他 sender 不能抢占 owner。`CREATOR_ADMIN_KEYS` 只保存稳定 sender ID，不保存完整 QQ 消息；`BILIBILI_COOKIE` 只由 Python 进程读取，不进入数据库、日志或日报。

## 4. Skills 源文件和安装目标发现

项目源文件在：

~~~~text
E:\YilenaCode\DailyIntelligence\skills\
├── daily-intelligence-local\SKILL.md
├── dailyintelligence-creators\SKILL.md
│   └── references\commands.md
├── github-radar\SKILL.md
├── tech-news-radar\SKILL.md
└── interest-profile\SKILL.md
~~~~

Hermes v0.23.0 的配置示例说明 external_dirs 是只读外部 Skills 目录。安装前请在当前 Profile 的配置中查找字段，不要直接套用其他 Profile：

~~~~powershell
Select-String -Path "E:\HermesData\*.yaml","E:\HermesData\profiles\*\*.yaml" -Pattern "external_dirs" -ErrorAction SilentlyContinue
~~~~

优先将项目 Skills 目录加入当前 Profile 的 skills.external_dirs。若组织规范不允许外部目录，再把五个子目录复制到目标 Profile 的 skills 目录，并保留源目录作为版本控制副本。复制目标必须通过当前 Hermes Profile 的配置或 help 输出确认。

本地调度 Skill 的精确来源路径是：

`E:\YilenaCode\DailyIntelligence\skills\daily-intelligence-local`

创作者管理 Skill 的精确来源路径是：

`E:\YilenaCode\DailyIntelligence\skills\dailyintelligence-creators`

如果当前 Hermes 版本支持按本地来源筛选，使用 `--source local` 和目标 Profile 验证；如果只支持 `skills.external_dirs` 目录级加载，则把项目 `skills` 目录配置为外部目录，并通过本地 Skill 的唯一名称 `daily-intelligence-local` 消除 Hub 冲突。本项目不猜测或修改 Hermes 的 Profile 配置。

确认 Hermes 能看到 Skill：

~~~~powershell
hermes skills list
hermes skills list --source local --enabled-only -p <profile>
hermes skills inspect daily-intelligence-local
hermes skills inspect dailyintelligence-creators
~~~~

具体命令以目标 Hermes 版本的 help 输出为准；本项目不自动执行安装。

## 5. Python CLI 运行方式

所有命令显式指定代码目录和运行数据目录，避免把数据库写进代码目录：

~~~~powershell
Set-Location "E:\YilenaCode\DailyIntelligence"
python -m daily_intelligence --data-dir "E:\HermesData\daily-intelligence" collect-github
python -m daily_intelligence --data-dir "E:\HermesData\daily-intelligence" collect-rss
python -m daily_intelligence --data-dir "E:\HermesData\daily-intelligence" import-handoff --file "E:\HermesData\daily-intelligence\config\hermes-handoff.json"
python -m daily_intelligence --data-dir "E:\HermesData\daily-intelligence" recommend --json
python -m daily_intelligence --data-dir "E:\HermesData\daily-intelligence" report
python -m daily_intelligence --data-dir "E:\HermesData\daily-intelligence" query "MCP"
~~~~

采集命令有按日期的 runs 幂等保护；失败会保存 failed 状态，下次执行允许重试。

手动 QQ 私聊触发“生成今天的日报”时，Skill 必须使用以下顺序，不能根据日期自行拼接路径：

~~~~powershell
$generation = python -m daily_intelligence --data-dir "E:\HermesData\daily-intelligence" report --json
# 校验 JSON 的 ok=true，并把本次返回的 qq_report_path 原样传给下一步
python -m daily_intelligence read-report --path "<qq_report_path>" --json
~~~~

`read-report` 会用 UTF-8 完整读回本次 `.qq.md`，返回原始 `content`、字符数和按 QQ 长度拆好的 `messages`。Hermes 应将“今日日报已生成，以下是完整日报正文：”拼接到第一段，再按数组顺序通过当前入站会话发送这些消息；不要单独发送一个提示消息。正文必须保留日期、章节、链接、`partial` 状态和创作者动态；最后一段带有“日报发送完成。”。生成失败、路径缺失、读取失败、正文为空或某段发送失败时，只报告实际错误和文件路径，不把文件落盘当作用户已收到，也不重新运行生成程序。

## 6. 数据库初始化命令

~~~~powershell
python -m daily_intelligence --data-dir "E:\HermesData\daily-intelligence" init-db
~~~~

数据库迁移由 daily_intelligence.database.Database.initialize 负责。不要手工删除 schema_version、WAL 文件或直接修改表结构。

## 7. Cron 配置方式

日报 Cron 只负责生成和保存日报，不主动向 QQ Bot 推送消息；手动私聊回复由当前入站会话单独完成。请在 Hermes 当前 Profile 中使用已有 cronjob 工具、hermes cron add 或 /cron，并先用目标版本的 help 确认参数：

~~~~powershell
hermes cron --help
hermes cron list
~~~~

建议任务提示词：

~~~~text
在 E:\YilenaCode\DailyIntelligence 工作目录执行：
1. python -m daily_intelligence --data-dir E:\HermesData\daily-intelligence collect-github
2. python -m daily_intelligence --data-dir E:\HermesData\daily-intelligence collect-rss
3. 使用 Hermes 原生 `web_search` 对 AI、Agent、软件开发各执行至少两组查询。
4. 对重要结果使用 `web_extract` 核实原始页面，按 schema 1.0 写入 E:\HermesData\daily-intelligence\config\hermes-handoff.json。
5. python -m daily_intelligence --data-dir E:\HermesData\daily-intelligence import-handoff --file E:\HermesData\daily-intelligence\config\hermes-handoff.json
6. python -m daily_intelligence --data-dir E:\HermesData\daily-intelligence report
只保存日报和运行结果；没有完成目标、权限和消息适配器验收前，不向任何外部平台主动发送消息。
~~~~

如果使用 Hermes 的 script 字段，script 必须是 Hermes Home scripts 目录中的文件，而不是把命令行字符串直接放进 script。Cron 的 workdir 应设置为 E:\YilenaCode\DailyIntelligence，timezone 建议设置为 Asia/Shanghai。

## 8. QQ Bot 接入方式

当前 QQ Bot 已由 Hermes 接入，配置示例包含 qqbot 工具集。Daily Intelligence 不新增 QQ Bot、WebSocket、主动推送或消息 Adapter：

1. 用户在 QQ 私聊中主动询问日报或反馈兴趣。
2. Hermes 使用当前真实入站消息上下文加载 daily-intelligence-local Skill。
3. 用户要求生成日报时，Skill 调用 `report --json`，再用返回的 `qq_report_path` 调用 `read-report --json`，把完整 `messages` 按顺序作为当前会话的被动回复。
4. 不伪造 message_id，不复用过期上下文，不尝试绕过腾讯官方 API v2 的回复限制。

如果目标环境的入站消息不能交给 Hermes，先检查 Hermes qqbot 平台和 Profile toolset；不要在本项目内重写 QQ 路由。

创作者账号管理由独立的 `dailyintelligence-creators` Skill 路由到 `creator --json` CLI。自然语言意图包括“添加这个 UP 主/频道”“查看监控账号”“删除/暂停/恢复账号”和“只监控视频/动态”；Skill 必须从当前私聊入站上下文传入真实 sender ID，不能让用户在文本中自报 owner。没有预置授权时，该 ID 会在首次管理请求时自动登记。Skill 会先用列表结果解析名称/链接目标，多匹配时要求用户选择，删除始终要求明确确认。Bilibili 默认视频与动态均开启，YouTube 仅视频。账号管理不会创建新的定时任务，也不会发送实时通知。每次调用都要检查退出码和 JSON `ok`，失败时不得反馈成功。

腾讯 QQ 开放平台官方文档列出的消息类型包括文本、Markdown 和媒体；接口的主动推送、Markdown 模板审批、URL 白名单、媒体上传和频率限制必须按目标机器人和 Hermes adapter 的实际配置验证，不能只凭本地文件生成成功来宣称已打通。参考：[QQ 官方消息发送与接收文档](https://github.com/tencent-connect/bot-docs/blob/main/docs/develop/api-v2/server-inter/message/send-receive/send.md)。本项目当前只完成：

官方文档当前还注明主动推送能力自 2025-04-21 起不可用；因此本项目把定时任务默认边界设为本地落盘和入站场景下的被动回复，除非目标平台和适配器提供了经过验证的替代投递能力。

- 生成 `reports/YYYY-MM-DD.qq.md` 完整阅读版。
- 用 `read-report` 读取本次生成路径对应的完整正文。
- 按 `##`/`###` 章节和完整项目/新闻条目拆分消息，保留日期、原始链接、代码块和创作者状态。
- 最后一段标明“日报发送完成。”；发送失败时返回段序号和文件路径。
- 提供本地附件文件，等待 Hermes adapter 按官方媒体上传机制处理。

本项目尚未实现或验证：图片/文件的 QQ 媒体上传、真实私聊主动推送、Cron 上下文消息发送、目标会话发现和发送失败重试。创作者平台真实接口、Bilibili Cookie 风控状态、YouTube 频道页面解析也需要目标环境单独验收。未经用户授权不发送真实 QQ 测试消息。

## 9. 五个 Skills 的职责和结构化交接

| Skill | 职责 |
| --- | --- |
| `daily-intelligence-local` | 总入口、用户查询、Cron 编排、调用 `web_search`/`web_extract`、运行 `import-handoff`/`report`、生成 QQ 预览 |
| `dailyintelligence-creators` | 只管理 Bilibili/YouTube 创作者账号；识别链接、确认目标、传入可信 sender ID、调用 `creator --json` 并反馈真实结果 |
| `github-radar` | GitHub 候选、元数据、Release、最终候选 README、项目分析证据和热点/有趣项目分区 |
| `tech-news-radar` | RSS 补充、三个领域各至少两组 Web Search 查询、原文核实、时间和状态、跨来源去重 |
| `interest-profile` | 查询信号、喜欢/收藏/不感兴趣/深入了解、主题权重、排除和探索推荐 |

Hermes 写入交接 JSON 时使用项目 `daily_intelligence.handoff` 的 schema 1.0。根字段包括 `schema_version`、`generated_at`、`timezone`、`window_hours`、`search_status`、`search_queries`、`news`、`projects` 和 `collection_stats`。写入采用同目录临时文件加原子替换，Python 导入前会校验 URL、状态、字段长度和 owner/repo 格式，不接受凭证字段。

## 10. 用户主动查询

QQ 私聊中的自然语言由 `daily-intelligence-local` 识别后路由：完整日报走全流程；只问 AI、Agent 或软件开发时只搜索对应领域；项目/新闻深度分析只打开目标原始来源；兴趣反馈转为 `feedback` 或 `query`。例如：

~~~~powershell
python -m daily_intelligence --data-dir "E:\HermesData\daily-intelligence" query "Agent"
python -m daily_intelligence --data-dir "E:\HermesData\daily-intelligence" feedback "我对纯套壳项目不感兴趣"
~~~~

`query` 和反馈只存主题键、次数、短依据和时间，不保存完整聊天记录。

## 11. 测试命令

在项目目录执行：

~~~~powershell
python -m unittest discover -s tests -v
python -m daily_intelligence --version
python -m daily_intelligence --data-dir "$env:TEMP\daily-intelligence-manual" dry-run
~~~~

测试不会向真实 GitHub、RSS、QQ Bot 或 Hermes 发送请求。真实网络、Cron 和 QQ 流程需要部署后单独观察。

## 12. 回滚方法

代码回滚：

~~~~powershell
Set-Location "E:\YilenaCode\DailyIntelligence"
git log --oneline --decorate -10
git checkout <known-good-commit>
python -m unittest discover -s tests -v
~~~~

Skill 回滚：从 Hermes Profile 的 skills.external_dirs 中移除项目路径，或恢复复制前的四个 Skill 目录，然后按目标 Hermes 版本要求刷新 Skill 缓存或重启对应 Profile。

运行数据回滚：优先保留 E:\HermesData\daily-intelligence 的 database、config 和 reports 作为证据；需要回退数据时先停止相关 Cron，备份整个目录，再恢复备份。不要使用 git reset 删除运行数据。

## 13. 不在本项目范围内的操作

- 不修改 E:\HermesData\config.yaml、Profile 配置或 QQ Bot 凭据。
- 不安装第三方服务、数据库、Docker、队列或独立 Web 服务。
- 不直接发送 QQ 消息。
- 不把运行数据或敏感凭据提交到 Git。

