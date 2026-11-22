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
| Skills 源目录 | E:\YilenaCode\DailyIntelligence\skills |

代码与运行数据必须保持分离。不要把数据库、Token、日报或日志提交回 Git 仓库。

## 2. 安装前检查

本次只读勘察得到：

- Windows 当前 Python 3.13.7。
- Hermes 源码版本 v0.23.0。
- Hermes Home 为 E:\HermesData。
- Hermes 配置示例支持 skills.external_dirs，并将外部目录作为只读 Skills 源。
- Hermes 的 qqbot 工具集已经存在，当前项目不需要新增消息 Adapter。

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

## 4. Skills 源文件和安装目标发现

项目源文件在：

~~~~text
E:\YilenaCode\DailyIntelligence\skills\
├── daily-intelligence-local\SKILL.md
├── github-radar\SKILL.md
├── tech-news-radar\SKILL.md
└── interest-profile\SKILL.md
~~~~

Hermes v0.23.0 的配置示例说明 external_dirs 是只读外部 Skills 目录。安装前请在当前 Profile 的配置中查找字段，不要直接套用其他 Profile：

~~~~powershell
Select-String -Path "E:\HermesData\*.yaml","E:\HermesData\profiles\*\*.yaml" -Pattern "external_dirs" -ErrorAction SilentlyContinue
~~~~

优先将项目 Skills 目录加入当前 Profile 的 skills.external_dirs。若组织规范不允许外部目录，再把四个子目录复制到目标 Profile 的 skills 目录，并保留源目录作为版本控制副本。复制目标必须通过当前 Hermes Profile 的配置或 help 输出确认。

本地调度 Skill 的精确来源路径是：

`E:\YilenaCode\DailyIntelligence\skills\daily-intelligence-local`

如果当前 Hermes 版本支持按本地来源筛选，使用 `--source local` 和目标 Profile 验证；如果只支持 `skills.external_dirs` 目录级加载，则把项目 `skills` 目录配置为外部目录，并通过本地 Skill 的唯一名称 `daily-intelligence-local` 消除 Hub 冲突。本项目不猜测或修改 Hermes 的 Profile 配置。

确认 Hermes 能看到 Skill：

~~~~powershell
hermes skills list
hermes skills list --source local --enabled-only -p <profile>
hermes skills inspect daily-intelligence-local
~~~~

具体命令以目标 Hermes 版本的 help 输出为准；本项目不自动执行安装。

## 5. Python CLI 运行方式

所有命令显式指定代码目录和运行数据目录，避免把数据库写进代码目录：

~~~~powershell
Set-Location "E:\YilenaCode\DailyIntelligence"
python -m daily_intelligence --data-dir "E:\HermesData\daily-intelligence" collect-github
python -m daily_intelligence --data-dir "E:\HermesData\daily-intelligence" collect-rss
python -m daily_intelligence --data-dir "E:\HermesData\daily-intelligence" recommend --json
python -m daily_intelligence --data-dir "E:\HermesData\daily-intelligence" report
~~~~

采集命令有按日期的 runs 幂等保护；失败会保存 failed 状态，下次执行允许重试。

## 6. 数据库初始化命令

~~~~powershell
python -m daily_intelligence --data-dir "E:\HermesData\daily-intelligence" init-db
~~~~

数据库迁移由 daily_intelligence.database.Database.initialize 负责。不要手工删除 schema_version、WAL 文件或直接修改表结构。

## 7. Cron 配置方式

日报 Cron 只负责生成和保存日报，不主动向 QQ Bot 推送消息。请在 Hermes 当前 Profile 中使用已有 cronjob 工具、hermes cron add 或 /cron，并先用目标版本的 help 确认参数：

~~~~powershell
hermes cron --help
hermes cron list
~~~~

建议任务提示词：

~~~~text
在 E:\YilenaCode\DailyIntelligence 工作目录执行：
1. python -m daily_intelligence --data-dir E:\HermesData\daily-intelligence collect-github
2. python -m daily_intelligence --data-dir E:\HermesData\daily-intelligence collect-rss
3. python -m daily_intelligence --data-dir E:\HermesData\daily-intelligence report
只保存日报和运行结果，不向任何外部平台主动发送消息。
~~~~

如果使用 Hermes 的 script 字段，script 必须是 Hermes Home scripts 目录中的文件，而不是把命令行字符串直接放进 script。Cron 的 workdir 应设置为 E:\YilenaCode\DailyIntelligence，timezone 建议设置为 Asia/Shanghai。

## 8. QQ Bot 接入方式

当前 QQ Bot 已由 Hermes 接入，配置示例包含 qqbot 工具集。Daily Intelligence 不新增 QQ Bot、WebSocket、主动推送或消息 Adapter：

1. 用户在 QQ 私聊中主动询问日报或反馈兴趣。
2. Hermes 使用当前真实入站消息上下文加载 daily-intelligence-local Skill。
3. Skill 读取本地日报、SQLite 和画像后生成被动回复。
4. 不伪造 message_id，不复用过期上下文，不尝试绕过腾讯官方 API v2 的回复限制。

如果目标环境的入站消息不能交给 Hermes，先检查 Hermes qqbot 平台和 Profile toolset；不要在本项目内重写 QQ 路由。

## 9. 测试命令

在项目目录执行：

~~~~powershell
python -m unittest discover -s tests -v
python -m daily_intelligence --version
python -m daily_intelligence --data-dir "$env:TEMP\daily-intelligence-manual" dry-run
~~~~

测试不会向真实 GitHub、RSS、QQ Bot 或 Hermes 发送请求。真实网络、Cron 和 QQ 流程需要部署后单独观察。

## 10. 回滚方法

代码回滚：

~~~~powershell
Set-Location "E:\YilenaCode\DailyIntelligence"
git log --oneline --decorate -10
git checkout <known-good-commit>
python -m unittest discover -s tests -v
~~~~

Skill 回滚：从 Hermes Profile 的 skills.external_dirs 中移除项目路径，或恢复复制前的四个 Skill 目录，然后按目标 Hermes 版本要求刷新 Skill 缓存或重启对应 Profile。

运行数据回滚：优先保留 E:\HermesData\daily-intelligence 的 database、config 和 reports 作为证据；需要回退数据时先停止相关 Cron，备份整个目录，再恢复备份。不要使用 git reset 删除运行数据。

## 11. 不在本项目范围内的操作

- 不修改 E:\HermesData\config.yaml、Profile 配置或 QQ Bot 凭据。
- 不安装第三方服务、数据库、Docker、队列或独立 Web 服务。
- 不直接发送 QQ 消息。
- 不把运行数据或敏感凭据提交到 Git。

