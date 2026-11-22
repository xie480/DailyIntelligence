# Daily Intelligence 报告幂等修复记录

## 背景与目标

2026-11-22 的部署检查发现：同一日期的 `report` 首次执行写入 15 条 `action='recommended'` 反馈，随后经 Hermes Cron 再次执行时报告文件内容不变，但推荐历史增至 30 条。该日期的 RSS 项目均为 7-day supplement，未进入日报板块，却仍被记录为已推荐。

目标是让同一报告日期的重复执行不再追加重复推荐历史，并让推荐历史只反映实际写入日报的项目。修复不修改 Hermes、QQ Bot、凭据或运行数据，也不删除或改写已有反馈记录。

## 根因

- `daily_intelligence/cli.py::_report` 原先先调用 `RecommendationEngine.recommend(record=True)`，之后才调用 `DailyReportRenderer.render`。
- `DailyReportRenderer` 会过滤非重大 RSS supplement、重复 URL 和板块容量之外的项目；这些项目在渲染前已经被推荐引擎写入历史。
- 推荐冷却只按项目 ID 过滤；带有新 Release 或显著 Star 增长的项目会按既有规则绕过冷却，因此同一天重复报告仍可能再次写入。
- 反馈记录原先没有报告日期键，无法表达“该项目已在这一天的报告中展示”。

## 修复方案

1. `DailyReportRenderer.select_rendered_items` 复用日报的过滤、去重、板块容量和总量限制，得到实际会出现在报告中的项目。
2. `_report` 改为先计算推荐但暂不记录，完成渲染筛选后只记录 `select_rendered_items` 的结果。
3. 报告推荐历史的 `signal` 增加 `report_date`。同一项目已有该日期标记时跳过写入；对修复前同日产生且没有标记的旧记录，以 `created_at` 日期作为兼容判断，不修改旧行。
4. 普通 `recommend` 的公开参数、输出和 30 天推荐冷却及 Release/Star 增长例外保持不变；只有报告工作流使用日期幂等记录。

## 回归测试

- `CLITestCase.test_report_same_date_is_idempotent_for_recommendation_history`：使用可绕过推荐冷却的新 Release 项目，连续执行同一日期报告，验证 Markdown 不变且推荐历史数量不增加。
- `CLITestCase.test_report_does_not_record_filtered_rss_supplement`：使用非重大 7-day supplement，验证项目不出现在报告且不产生 `recommended` 历史。

## 验证范围与限制

- 回归测试和完整 unittest 使用隔离的 `.test-tmp` 目录，不接触真实运行数据目录。
- 本修复未执行真实 RSS/GitHub 网络采集、Hermes Cron、QQ Bot 或 Windows 部署运行；这些运行时边界仍需在目标环境单独复核。
- 已存在的重复反馈保留作为历史证据；本修复只阻止后续同日报告继续追加。

## 验证结果

- `python -m unittest discover -s tests -v`：30 项通过，exit code `0`。
- `python -m daily_intelligence --version`：输出 `daily_intelligence 1.0.0`，exit code `0`。
- `python -m daily_intelligence --data-dir .test-tmp\final-dry-run dry-run`：生成隔离样例日报且未创建运行数据库，exit code `0`。
- `git diff --check`：exit code `0`。
- unittest 输出了现有的 `ResourceWarning`（限流测试中的 `HTTPError` 清理提示），没有失败测试。
