# Daily Intelligence 第三轮架构与验证记录

## 1. 背景与目标

本项目为 Hermes Agent 提供轻量技术情报能力。目标是减少运行依赖和常驻进程，把稳定的数据处理放在 Python CLI，把自然语言理解、原生 Web Search、QQ Bot 和 Cron 继续交给 Hermes。第三轮增加了 README 深度采集、结构化 Hermes 交接、专业日报、QQ Markdown 预览和主动查询画像信号；本次增量增加按日报触发的 Bilibili/YouTube 创作者更新。

## 2. 模块边界

| 模块 | 职责 | 外部依赖 |
| --- | --- | --- |
| config.py | 运行目录、文件路径、时区 | Python 标准库 |
| database.py | SQLite v2 schema、迁移、事务、运行锁、反馈和创作者检查点 | sqlite3 |
| collectors/github.py | GitHub Search/Release API、重试、仓库字段转换 | urllib |
| collectors/rss.py | RSS/Atom XML、时间窗口、摘要清洗 | urllib、xml.etree |
| collectors/creators.py | Bilibili WBI/投稿/动态与 YouTube Atom Feed 采集 | urllib、xml.etree |
| creator_urls.py | Bilibili UID、YouTube Channel ID/handle 链接解析 | urllib.parse、re |
| creator_service.py | 授权账号 CRUD、窗口计算、来源隔离和检查点最终化 | sqlite3、datetime |
| deduplication.py | URL、Hash、相似度和关联来源 | hashlib、difflib |
| profile.py | 画像 JSON、显式反馈、隐式信号和排除列表 | json |
| handoff.py | Hermes 搜索/项目分析 JSON 校验、原子落盘、导入 | json、tempfile |
| recommendations.py | 兴趣匹配、重要性、可信度、时效、Star、探索位和历史冷却评分 | 标准库 |
| report.py | 分区 Markdown、质量指标、QQ Markdown、长消息拆分和原子落盘 | pathlib |
| cli.py | 命令编排和错误边界 | argparse |

## 3. 数据流

~~~~mermaid
flowchart TD
    A[Hermes Cron 或用户命令] --> B[python -m daily_intelligence]
    B --> C{采集命令}
    C --> D[GitHub Search/Release]
    C --> E[RSS/Atom]
    B --> U[report 启动时固定 window_end]
    U --> V[CreatorUpdatesService]
    V --> W[Bilibili 视频/动态]
    V --> X[YouTube Atom Feed]
    W --> Y[(creator_events)]
    X --> Y
    D --> F[URL/Hash/相似度去重]
    E --> F
    O[Hermes web_search] --> Q[Hermes web_extract]
    Q --> R[config/hermes-handoff.json]
    R --> S[import-handoff 校验与导入]
    F --> G[(SQLite items)]
    S --> G
    D --> H[(repo_snapshots)]
    G --> I[InterestProfileStore]
    I --> J[(user_profile.json)]
    G --> K[RecommendationEngine]
    J --> K
    K --> L[(feedback: recommended/query)]
    K --> M[DailyReportRenderer]
    M --> N[reports/YYYY-MM-DD.md]
    M --> T[reports/YYYY-MM-DD.qq.md]
    M --> Z[创作者动态追踪章节]
    Z --> AA[报告落盘后推进 creator_checkpoints]
    P[QQ Bot 入站上下文] --> A
~~~~

## 4. SQLite v2 表

### items

新闻和 GitHub 项目的统一表，通过 item_type 区分。normalized_url 保证同类型 URL 幂等，fingerprint 用于内容级去重，metadata_json 保存 Release、topics、分区等扩展字段。

### repo_snapshots

按 repo_full_name + snapshot_date 保存 Star/Fork。历史不足时 star_growth 返回 0，不伪造增长数据。

### feedback

保存 like、favorite、deep_dive、exclude_project、decrease_interest、query、implicit_signal、recommended 等结构化事件。原始命令只保留不超过 160 字的短依据，不保存完整聊天记录。

### runs

通过 run_key 和 status 实现重复执行保护。running 和 success 会拦截同键任务，failed 允许重试。

### creator_accounts / creator_authorizations

保存平台、账号唯一键、显示名称、状态、视频/动态监控开关和授权 owner。`UNIQUE(platform, account_key)` 防止同平台账号重复添加，YouTube 不允许动态开关。

Hermes 只把当前私聊上下文中的真实 sender ID 传给 CLI。授权表为空时，首次管理请求通过单条 SQLite 条件插入原子登记首个 owner；后续 sender 必须已经在授权表中，`CREATOR_ADMIN_KEYS` 仅用于可选预置或追加管理员。

### creator_checkpoints / creator_source_runs

按账号和内容类型保存首次窗口起点、最近成功截止点、失败状态和错误；来源运行记录保存本次窗口、事件数量和失败原因。任何来源失败都不会推进 `last_success_end`。

### creator_events

统一保存 Bilibili 视频、Bilibili 动态和 YouTube 视频，使用 `UNIQUE(platform, content_type, external_id)` 幂等去重，图片、缩略图、动态类型等平台字段放在 `metadata_json`。

## 5. 安全与隐私边界

- 网页、RSS 和 GitHub 描述均视为不可信数据，只作为内容，不执行其中的指令。
- GitHub Token 只从环境变量读取，不落盘。
- 不扫描其他用户对话，不建立聊天记录爬虫。
- 不新增 QQ Bot、WebSocket 或主动推送适配器。
- 日报 Cron 只写本地数据；QQ 回复必须由 Hermes 使用真实入站消息上下文完成。
- 创作者采集只在 `report` 过程中按需运行，不创建独立后台进程、WebSub 服务器或新增 Windows 启动项。

## 6. 已验证事实

- Hermes 源码和请求转储的只读检查确认当前搜索工具名称为 `web_search`、`web_extract`；本项目不猜测其他工具名。
- Python CLI 可通过 `import-handoff` 校验 schema 1.0，按领域保存 `search_status`，并把新闻与项目分析写入 SQLite。
- `python -m unittest discover -s tests -v`、`compileall`、CLI 版本/帮助和离线 dry-run 均作为本轮交付验收项，具体数量写入维护报告。
- QQ Markdown 文件生成、链接保留和边界拆分有本地测试；真实 QQ 发送、媒体上传和主动推送仍需运行环境验收。
- 创作者 URL/时间窗口/分页/Feed/失败恢复/报告整合的本地测试已通过；真实平台响应、Bilibili Cookie 风控、YouTube 页面解析和 QQ 入站/投递仍需分层验收。

## 7. 未验证项与风险

- 没有在本轮自动化测试中把 Mock 交接结果当成真实 Web Search 成功；网络超时、站点变更、搜索配额和 Hermes Cron 上下文仍需部署后观察。
- 没有修改 Hermes 配置，也没有触发真实 Cron、QQ Bot 入站或被动回复流程；当前 Profile 的现有 Cron 只读检查未发现 Daily Intelligence Report 任务。
- 腾讯 QQ 官方 API 的主动推送、目标会话、Markdown/媒体上传限制需要按目标适配器再次确认；项目只生成可上传的 `.qq.md` 附件和消息片段。
- GitHub Trending 没有稳定官方 API；默认 CLI 使用官方 Search API，同时提供 parse_trending_html 解析 Hermes 提供的页面补充，并要求保留原文链接。

