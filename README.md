# Daily Intelligence

Daily Intelligence 是一个面向 Hermes Agent 的轻量技术情报系统 v1.0。它使用 Python 标准库、SQLite、JSON 和 Markdown，代码与运行数据分离，不增加常驻服务、Web Dashboard 或额外机器人。

## 目标与边界

- 采集 GitHub AI/Agent/MCP/开发工具项目，以及 RSS/Atom 技术新闻。
- 默认使用 GitHub 官方 Search API，并提供 Trending HTML 补充解析入口。
- 通过 URL、内容指纹和标准库文本相似度做三层去重。
- 通过 JSON 画像和 SQLite 反馈历史进行可解释推荐。
- 生成 YYYY-MM-DD.md 日报，供 Hermes Skill 或用户主动查询。
- QQ Bot 继续使用 Hermes 已有的消息路由；本项目不创建 Adapter、不伪造消息、不主动绕过平台限制。
- 不扫描其他用户聊天记录，只保存结构化兴趣信号和短依据。

## 目录

~~~~text
DailyIntelligence/
├── daily_intelligence/
│   ├── collectors/
│   │   ├── github.py
│   │   └── rss.py
│   ├── cli.py
│   ├── config.py
│   ├── database.py
│   ├── deduplication.py
│   ├── models.py
│   ├── profile.py
│   ├── recommendations.py
│   └── report.py
├── skills/
├── tests/
├── config/
├── deployment/
├── docs/
├── README.md
└── CHANGELOG.md
~~~~

## 快速开始

默认运行数据目录是 E:\HermesData\daily-intelligence。也可以为测试或多套 Hermes Profile 指定其他目录。

~~~~powershell
python -m daily_intelligence --data-dir "E:\HermesData\daily-intelligence" init-db
python -m daily_intelligence --data-dir "E:\HermesData\daily-intelligence" collect-github
python -m daily_intelligence --data-dir "E:\HermesData\daily-intelligence" collect-rss
python -m daily_intelligence --data-dir "E:\HermesData\daily-intelligence" report
~~~~

只查看推荐，不写推荐历史：

~~~~powershell
python -m daily_intelligence --data-dir "E:\HermesData\daily-intelligence" recommend --no-record
~~~~

离线检查日报渲染，不访问网络或写运行数据：

~~~~powershell
python -m daily_intelligence --data-dir ".test-tmp\manual" dry-run
~~~~

## CLI 命令

| 命令 | 作用 |
| --- | --- |
| init-db | 创建 SQLite、画像 JSON、目录和默认 sources.json |
| collect-github | 使用 GitHub 官方 Search API，保存项目和每日 Star 快照 |
| collect-rss | 读取 RSS/Atom，保留 24 小时主体和 7 天补充窗口 |
| recommend | 获取待推荐内容，支持 --type、--limit、--json |
| feedback TEXT | 解析明确反馈，可用 --target 指定项目 |
| profile show/reset/enable/disable | 查看或管理画像 |
| report | 按推荐结果保存 Markdown 日报，支持 --date YYYY-MM-DD |
| dry-run | 使用固定样例渲染日报，不建立运行数据 |

全局参数必须放在子命令前：

~~~~powershell
python -m daily_intelligence --data-dir "E:\HermesData\daily-intelligence" --timezone "Asia/Shanghai" report
~~~~

## 配置与运行数据

代码目录固定为 E:\YilenaCode\DailyIntelligence，运行数据默认位于 E:\HermesData\daily-intelligence：

- database/intelligence.db：SQLite 数据库。
- config/user_profile.json：当前用户画像。
- config/sources.json：实际采集源；可由 config/sources.example.json 初始化。
- reports/YYYY-MM-DD.md：每日日报。
- logs/daily-intelligence.log：CLI 运行日志。

GitHub Token 是可选的。设置 GITHUB_TOKEN 可以提高 API 配额，不设置时仍使用公开 API。Token 不写入源码、JSON 模板或日报。

## 测试

项目没有第三方运行时依赖，使用 Python unittest：

~~~~powershell
python -m unittest discover -s tests -v
~~~~

当前测试使用 Fake opener，不向真实 GitHub、RSS、QQ Bot 或 Hermes 发送请求。

## Hermes 使用方式

将 skills/ 作为 Hermes 外部只读 Skills 目录，或按 deployment/HERMES_INSTALL.md 复制到目标 Profile 的 Skills 目录。日报 Cron 只执行采集、推荐和保存；QQ Bot 用户主动提问时由 daily-intelligence Skill 读取日报和数据库后被动回复。

完整模块边界、数据流和未验证项见 docs/architecture.md。

## Git 交付

开发过程按逻辑阶段形成了本地提交，提交消息使用 feat/fix/chore: 中文描述格式。未配置远程仓库，也未执行 Push。

