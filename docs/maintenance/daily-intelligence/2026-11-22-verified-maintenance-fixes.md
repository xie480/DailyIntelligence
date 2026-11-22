# Daily Intelligence 维护修复记录

## 背景与目标

本次维护针对已确认的五个离线行为问题做最小修复，保持现有 CLI/API、Hermes 配置、QQ Bot 设置、凭据和运行数据不变：

1. 修复 `schema_version=1` 但 v1 表或索引不完整时的数据库初始化。
2. 为每个 SQLite 连接启用外键约束。
3. 修复没有窗口 cutoff 之前快照时的 `star_growth` 基线计算。
4. 限制日报“今日重点推荐”只能引用已渲染板块中的项目，并按规范化 URL 去重。
5. 让 CLI `DEFAULT_SOURCES` 与 `config/sources.example.json` 一致，包含 GitHub Blog feed。

## 根因与修改

- `daily_intelligence/database.py`
  - `initialize` 在版本号为 1 时原本不会再次执行 v1 DDL；现在对当前 v1 版本重复执行幂等 `CREATE TABLE/INDEX IF NOT EXISTS`，仅在版本低于 1 时写入版本记录，因此不会删除已有数据。
  - 连接建立后执行 `PRAGMA foreign_keys = ON`。
  - `star_growth` 找不到 cutoff 之前快照时返回 0，不再回退到最早的窗口内快照。
- `daily_intelligence/report.py`
  - 单独记录真正进入板块容量的项目；重点推荐只从这些项目中选择，并再次按规范化 URL 去重。
- `daily_intelligence/cli.py`
  - 默认 RSS 列表补充 `https://github.blog/feed/`。

## 回归覆盖

- `tests/test_foundation.py`
  - 部分 v1 schema 修复与已有项目数据保留。
  - 外键 pragma 和非法 `item_id` 插入拒绝。
  - 没有 cutoff 基线时增长为 0，同时保留有效历史增长断言。
- `tests/test_report.py`
  - 板块容量溢出项目不能进入重点推荐，规范化重复 URL 只保留一项。
- `tests/test_cli.py`
  - 默认 RSS feed 与示例配置逐项一致。

## 验证范围与限制

已执行的离线单元测试覆盖数据库、报告和 CLI 相关路径；CLI 版本和 dry-run 只验证本地入口与无网络渲染。未访问真实 GitHub/RSS 服务，也未触碰 Hermes、QQ Bot 或运行数据目录。
