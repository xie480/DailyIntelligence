# 创作者动态增量改造审计

## 1. 背景与目标

本次改造在现有 Daily Intelligence 上增加 Bilibili UP 主视频、Bilibili 动态和 YouTube 频道视频采集，并把结果整合到原有日报。代码目录仍为 `E:\YilenaCode\DailyIntelligence`，运行数据仍由 `RuntimePaths` 指向独立的 Hermes 数据目录，不修改 Hermes Gateway、Cron 或 QQ Bot 配置。

## 2. 现有架构与实际调用链

```text
Hermes Cron 或用户命令
    ↓
python -m daily_intelligence
    ↓
daily_intelligence.cli._report
    ├── _runtime → RuntimePaths + Database.initialize + InterestProfileStore
    ├── RecommendationEngine.recommend
    ├── DailyReportRenderer.render / render_qq
    ├── save_report / save_qq_report
    └── RecommendationEngine.record_recommendations
```

原有采集链路为：

```text
collect-github → GitHubCollector → Database.upsert_item → items/repo_snapshots
collect-rss    → RSSCollector    → Database.upsert_item → items
import-handoff → Hermes JSON 校验 → Database.upsert_item → items
report         → RecommendationEngine → DailyReportRenderer → reports/*.md
```

### 关键文件

| 文件 | 事实职责 |
| --- | --- |
| `daily_intelligence/cli.py` | argparse、运行目录初始化、采集命令和日报编排入口 |
| `daily_intelligence/database.py` | SQLite v1 schema、事务、幂等项目写入、运行锁和反馈历史 |
| `daily_intelligence/models.py` | GitHub/新闻 `Item` 领域模型 |
| `daily_intelligence/collectors/github.py` | GitHub Search/Release/README 采集和重试 |
| `daily_intelligence/collectors/rss.py` | RSS/Atom 解析、时间过滤和失败隔离 |
| `daily_intelligence/report.py` | 原有五类日报板块、QQ Markdown、消息边界拆分和原子写入 |
| `skills/daily-intelligence-local/SKILL.md` | Hermes 本地 Skill 的 Cron 编排和自然语言路由说明 |
| `deployment/HERMES_INSTALL.md` | Hermes 接入边界、安装、回滚和验证说明 |

## 3. 可复用能力

- `RuntimePaths`、`timezone_or_default`、`now_in_timezone` 已提供带 IANA 时区的运行路径和时间基础设施。
- `Database.transaction`、SQLite 外键、`runs` 状态和原子 Markdown 写入可复用。
- `DailyReportRenderer` 的 QQ Markdown 和消息拆分逻辑保持不变，只扩展一个独立章节渲染入口。
- 现有采集器使用可注入 `urllib` opener 和标准库解析方式，创作者采集器沿用同样的可测试边界。
- Hermes QQ Bot 不在本仓库内；账号管理通过本地 CLI/Skill 路由完成，不新增 Adapter 或机器人。

## 4. 增量设计

1. 在 SQLite v2 中新增 `creator_accounts`、`creator_checkpoints`、`creator_events`、`creator_source_runs` 和 `creator_authorizations`，不改变既有 v1 表。
2. 以 `platform + account_key + content_type` 记录独立检查点。首次模块运行最多回溯 24 小时；模块运行后新添加账号从 `created_at` 开始。
3. `CreatorUpdatesService` 在 `_report` 启动时固定 `window_end`，按账号和内容类型隔离失败；事件先幂等保存，报告主 Markdown 和 QQ Markdown 都成功落盘后才推进对应检查点。
4. Bilibili 采集支持投稿分页、动态游标、视频卡片分类和 BV 级去重；YouTube 使用公开 Atom Feed，标准频道 URL 直接使用 Channel ID，`@handle` 通过频道页面解析真实 ID。
5. 报告新增“创作者动态追踪”一级章节，失败状态显示为不完整，不把失败伪装成“今日暂无更新”；原有 GitHub、RSS、Web Search 章节和推荐历史保持原语义。
6. Hermes Skill 增加自然语言账号管理路由和显式 CLI 示例，授权身份由稳定的 `owner_key`/本地授权表校验，不读取或保存完整聊天记录。

## 5. 主要风险与验证边界

| 风险 | 处理方式 |
| --- | --- |
| Bilibili 接口结构或风控变化 | 严格校验响应、有限重试、记录来源失败，保留检查点 |
| YouTube `@handle` 无法解析 | 只接受解析出的真实 Channel ID，失败时明确提示，不写入错误账号 |
| 报告保存失败造成遗漏 | 检查点只在两份报告都成功保存后推进；事件写入使用唯一键可重试 |
| QQ Bot 集成不在仓库内 | 只更新 Skill 与本地报告产物，真实入站/出站仍需 Hermes 环境验收 |
| Bilibili Cookie | 只从环境变量或本地受保护配置读取，不写入数据库、日志或 Git |

本轮单元测试使用 Fixture/Stub，不依赖真实 Bilibili、YouTube、Hermes 或 QQ 网络；真实平台接口、Cron 和 QQ 投递属于部署后验证项。
