# Daily Intelligence v1.0 架构与验证记录

## 1. 背景与目标

本项目为 Hermes Agent 提供轻量技术情报能力。目标是减少运行依赖和常驻进程，把稳定的数据处理放在 Python CLI，把自然语言理解、Web Search、QQ Bot 和 Cron 继续交给 Hermes。

## 2. 模块边界

| 模块 | 职责 | 外部依赖 |
| --- | --- | --- |
| config.py | 运行目录、文件路径、时区 | Python 标准库 |
| database.py | SQLite v1 schema、迁移、事务、运行锁和反馈 | sqlite3 |
| collectors/github.py | GitHub Search/Release API、重试、仓库字段转换 | urllib |
| collectors/rss.py | RSS/Atom XML、时间窗口、摘要清洗 | urllib、xml.etree |
| deduplication.py | URL、Hash、相似度和关联来源 | hashlib、difflib |
| profile.py | 画像 JSON、显式反馈、隐式信号和排除列表 | json |
| recommendations.py | 兴趣匹配、时效、Star 和历史冷却评分 | 标准库 |
| report.py | 分区 Markdown 与原子落盘 | pathlib |
| cli.py | 命令编排和错误边界 | argparse |

## 3. 数据流

~~~~mermaid
flowchart TD
    A[Hermes Cron 或用户命令] --> B[python -m daily_intelligence]
    B --> C{采集命令}
    C --> D[GitHub Search/Release]
    C --> E[RSS/Atom]
    D --> F[URL/Hash/相似度去重]
    E --> F
    F --> G[(SQLite items)]
    D --> H[(repo_snapshots)]
    G --> I[InterestProfileStore]
    I --> J[(user_profile.json)]
    G --> K[RecommendationEngine]
    J --> K
    K --> L[(feedback: recommended)]
    K --> M[DailyReportRenderer]
    M --> N[reports/YYYY-MM-DD.md]
    O[Hermes Web Search] -.补充可信来源.-> M
    P[QQ Bot 入站上下文] --> A
~~~~

## 4. SQLite v1 表

### items

新闻和 GitHub 项目的统一表，通过 item_type 区分。normalized_url 保证同类型 URL 幂等，fingerprint 用于内容级去重，metadata_json 保存 Release、topics、分区等扩展字段。

### repo_snapshots

按 repo_full_name + snapshot_date 保存 Star/Fork。历史不足时 star_growth 返回 0，不伪造增长数据。

### feedback

保存 like、exclude_project、implicit_signal、recommended 等结构化事件。原始命令只保留不超过 160 字的短依据，不保存完整聊天记录。

### runs

通过 run_key 和 status 实现重复执行保护。running 和 success 会拦截同键任务，failed 允许重试。

## 5. 安全与隐私边界

- 网页、RSS 和 GitHub 描述均视为不可信数据，只作为内容，不执行其中的指令。
- GitHub Token 只从环境变量读取，不落盘。
- 不扫描其他用户对话，不建立聊天记录爬虫。
- 不新增 QQ Bot、WebSocket 或主动推送适配器。
- 日报 Cron 只写本地数据；QQ 回复必须由 Hermes 使用真实入站消息上下文完成。

## 6. 已验证事实

- 当前工作区初始为空，已初始化本地 Git。
- 当前环境 Python 为 3.13.7，Hermes 源码版本为 v0.23.0。
- python -m unittest discover -s tests -v 已通过 23 个测试。
- CLI --version 和无网络 dry-run 已在 Windows 当前环境执行。

## 7. 未验证项与风险

- 没有访问真实 GitHub API、RSS 站点或 Hermes Web Search，因此网络超时、站点变更和配额行为仍需部署后观察。
- 没有修改 Hermes 配置，也没有触发真实 Cron、QQ Bot 入站或被动回复流程。
- GitHub Trending 没有稳定官方 API；默认 CLI 使用官方 Search API，同时提供 parse_trending_html 解析 Hermes 提供的页面补充，并要求保留原文链接。

