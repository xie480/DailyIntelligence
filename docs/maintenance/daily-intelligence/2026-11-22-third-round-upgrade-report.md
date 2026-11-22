# Daily Intelligence 第三轮升级交付报告

## 1. 背景与目标

本轮围绕 GitHub 项目理解、Hermes 原生联网搜索、个性化推荐、专业日报和 QQ Markdown 阅读体验完成代码与文档升级。实现保持 Python 标准库、SQLite、JSON 和 Markdown，不增加第三方运行时依赖，不修改项目 `.env`、Hermes Gateway、Windows Scheduled Task 或真实 QQ 数据。

## 2. 分阶段提交

| 阶段 | 本地提交 | 内容 |
| --- | --- | --- |
| 方案 | `556598b docs：记录第三轮升级实施方案` | 约束、数据流、四阶段验收标准 |
| GitHub | `21a5beb feat：增强 GitHub 元数据与 README 深度采集` | README Base64 解析、元数据、Release 和候选限制 |
| Hermes 交接 | `b8b00d8 feat：接入 Hermes Web Search 结构化交接` | schema 1.0、原子 JSON、状态、去重和 import-handoff |
| 日报 | `ffba4fe feat：升级专业日报与 QQ Markdown 阅读版` | 分区报告、质量指标、QQ Markdown 和消息拆分 |
| 个性化 | `b6b328c feat：完善个性化推荐与查询反馈` | query、负向/深入反馈、重要性评分和探索位 |
| 文档交付 | 待提交 | Skills、README、部署说明、示例交接和 Mock 日报 |

全部提交只存在本地 `main`，未执行 `git push`。

## 3. 核心改造

### GitHub 项目

- 对最终候选读取 README，正确处理 Base64，限制正文长度，并保存 `readme.status`、`html_url`/`download_url` 等来源信息。
- 保存 `full_name`、仓库名、homepage、topics、license、Stars、Forks、open issues、watchers、创建时间、更新时间、推送时间和最新 Release 时间。
- GitHub 热点和有趣项目使用不同 section 与条数上限；报告层按 section 去重，不为了凑数补低质量条目。
- Hermes 分析结果通过 `project_analysis` 写回项目 metadata，包含 `summary`、`features`、`use_cases`、`recommendation_reason` 和 `evidence_urls`。

### Hermes Web Search

- 只读检查确认当前 Hermes 原生工具名为 `web_search` 和 `web_extract`，Skill 文档已按实际名称编排。
- 每个领域要求至少两组查询，AI、Agent、软件开发分别保存 `search_status` 和 `search_queries`。
- `config/hermes-handoff.example.json` 展示 schema 1.0，`import-handoff` 负责校验、原子保存、新闻去重和项目分析导入。
- 搜索失败、页面不可访问、时间无法核实和低可信度在报告中保留状态，不折叠成“没有新闻”。

### 个性化与日报

- `query TOPIC` 只记录主题、次数和短依据，连续三次查询才增加 2 分。
- 支持“我对这条内容不感兴趣”和“我想深入了解这个项目”；分别形成项目排除或正向深入反馈。
- 推荐加入重要性、来源核实和项目分析证据评分，并为高重要性的新领域内容保留探索位。
- 报告包含速览、GitHub 热点、有趣项目、三个新闻板块、重点推荐、采集状态和质量指标；QQ 版本保留完整条目和链接，可按标题边界拆分。

## 4. 模拟报告

以下文件使用明确的 Mock 数据生成，文件首行已标明“示例 / Mock”，不代表真实新闻或真实搜索成功：

- [完整日报示例](2026-11-22-mock-report.md)
- [QQ Markdown 示例](2026-11-22-mock-report.qq.md)
- [Hermes 交接 JSON 示例](../../../config/hermes-handoff.example.json)

## 5. 验证结果

### 已执行并通过

- `python -m unittest discover -s tests -v`：87/87 通过，0 失败，0 错误。
- `python -m compileall -q daily_intelligence tests`：通过。
- `python -m daily_intelligence --version`：输出 `daily_intelligence 1.0.0`。
- `python -m daily_intelligence --help`：显示 `import-handoff`、`query` 等命令。
- `python -m daily_intelligence --data-dir "$env:TEMP\daily-intelligence-third-round-dry-run" dry-run`：离线生成完整报告和 QQ Markdown 预览。
- 使用示例 JSON 在临时数据目录执行 `import-handoff`：成功导入 3 条示例新闻，状态校验通过。
- `git diff --check`：通过。

### 只完成静态或 Mock 验证

- README、项目元数据、推荐评分和交接校验均使用 Fake/Mock 测试覆盖；本轮未把 Mock 结果当作真实联网成功。
- QQ Markdown 文件、消息拆分和附件落盘已在本地测试覆盖；没有向真实 QQ 发送测试消息。

### 需要目标环境继续验证

- 本轮未重新执行真实 GitHub/RSS/Web Search 网络流程，网络配额、站点变化和 Hermes Cron 上下文仍需部署后观察。
- 当前只读检查到的 Hermes Cron 配置没有 Daily Intelligence Report 任务；未擅自创建或修改 Cron。
- 当前 Hermes CLI 受安装目录 `.install.lock` 写权限阻塞，未执行写入型安装或 Cron 操作。
- QQ 官方文档当前注明主动推送能力自 2025-04-21 起不可用；项目未实现或验证图片/文件媒体上传、Cron 主动私聊投递、目标会话发现和发送重试。

## 6. 风险与后续事项

1. 在目标 Hermes Profile 中确认四个 Skill 的外部目录、真实 Profile、`web_search`/`web_extract` 在 Cron 上下文是否可用。
2. 先执行一次只读 Web Search，生成交接 JSON，比较 `search_status`、来源链接、时间字段和 SQLite `runs`，再考虑任何消息适配器动作。
3. 若仍需定时 QQ 通知，应先根据目标平台能力确认可用的被动回复或替代投递路径，并取得目标、时区和消息预览授权。
4. 继续保留运行数据在 `E:\HermesData\daily-intelligence`，不要把真实数据库、Token、QQ 凭证或日报回写到代码仓库。

