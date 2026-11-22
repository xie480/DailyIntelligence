# 日报手动触发后的完整正文交付

## 背景与目标

用户在 QQ 私聊中发送“生成今天的日报”时，Daily Intelligence 原先只向 Hermes 返回主报告保存路径，Hermes 没有继续读取本次生成的 `.qq.md`，因此用户还要再次发消息查询正文。本次改造只补齐“生成结果 → 正文读取 → 当前会话回复”链路，不修改 GitHub、RSS、Web Search、创作者采集、日报结构或 Cron 调度。

## 现状与根因

现有调用链为：

```mermaid
flowchart LR
    User[QQ 私聊：生成今天的日报]
    Skill[daily-intelligence-local Skill]
    CLI[python -m daily_intelligence report]
    Renderer[DailyReportRenderer]
    Files[reports/YYYY-MM-DD.md 与 .qq.md]
    Reply[Hermes 当前会话回复]

    User --> Skill --> CLI --> Renderer --> Files
    CLI -. 原先只打印主报告路径 .-> Skill
    Skill -. 未读取 .qq.md .-> Reply
```

Python CLI 已经同时原子保存完整 Markdown 和 QQ Markdown，且 `daily_intelligence/report.py` 已有本地消息拆分能力；缺口是生成命令没有结构化返回 QQ 路径，也没有供 Hermes 调用的完整正文读取接口。仓库不包含 Hermes Gateway 或 QQ Adapter，不能在本项目内虚构新的发送工具。

## 方案设计

1. `report --json` 在不改变默认人类可读输出的前提下，返回本次生成的 `report_path`、`qq_report_path`、逻辑日期和 `ok`。路径来自本次 `save_report`/`save_qq_report` 的返回值，不从日期重新拼接。
2. 新增 `read-report --path PATH --json`（兼容别名 `read-qq-report`）。它只读取调用方传入的 `.qq.md`，使用 UTF-8 一次性读完整文件，拒绝空正文，并返回原始 `content`、字符数和 `messages`。
3. 消息拆分按二级/三级标题和完整行边界执行，代码块不在中间断开，原始链接不截断。每段携带 `DailyIntelligence YYYY-MM-DD` 和 `第 x/y 部分`，最后一段带“日报发送完成。”。
4. 手动 Skill 流程严格使用 `report --json` 返回的 `qq_report_path`，随后调用 `read-report`，按 `messages` 顺序交给当前入站 QQ 会话。Cron 仍只保存报告，不新增主动推送任务，避免同一报告重复投递。
5. 用户提示语拼接到第一段消息，不单独占用一个没有日期和序号的 QQ 消息；日报正文先按语义润色规则转成纯文本，再按返回的分段顺序发送。

## 异常处理

| 情况 | 处理 |
| --- | --- |
| 生成失败 | `report --json` 返回 `ok: false` 和 `REPORT_GENERATION_FAILED`，不进入读取步骤 |
| 路径缺失或非 `.qq.md` | `read-report` 返回 `REPORT_READ_FAILED` 和实际路径 |
| 文件读取失败或非 UTF-8 | 返回读取错误和路径，保留原文件 |
| 文件为空 | 返回“日报正文为空”，不反馈发送成功 |
| 正文超出单条消息限制 | 使用 `messages` 连续发送，保持章节顺序 |
| 单段发送失败 | Skill 报告失败段序号和 `qq_report_path`，文件保留供重试 |
| 创作者状态为 `partial` | 正文原样保留，不在发送前重写为成功 |

## 核心修改

- `daily_intelligence/cli.py`
  - 为 `report` 增加 `--json` 结构化成功/失败结果。
  - 新增 `read-report`/`read-qq-report` 命令。
- `daily_intelligence/report.py`
  - 保留原有 QQ 标题和正文结构。
  - 增强 Markdown 安全分段、日期/序号头和完成标记。
  - 新增 `read_qq_report` UTF-8 完整读取接口。
- `skills/daily-intelligence-local/SKILL.md`
  - 明确手动触发必须读取本次返回路径并逐段回复。
  - 明确生成失败、读取失败、空正文和发送失败处理；Cron 仍保存-only。
- `README.md`、`deployment/HERMES_INSTALL.md`
  - 补充 CLI 接口、手动回复顺序和部署边界。
- `tests/test_report.py`、`tests/test_cli.py`、`tests/test_skills.py`
  - 覆盖 UTF-8、完整正文、日期/章节/代码块/链接分段、路径返回、错误结果和 Skill 契约。

## 验证结果

- `python -m unittest tests.test_report tests.test_cli tests.test_skills -q`：43 个测试通过。
- `python -m unittest discover -s tests -q`：128 个测试通过。
- `python -m compileall -q daily_intelligence tests`：通过。
- `git diff --check`：未发现空白错误。

以上验证是本地单元测试和 CLI 静态/隔离运行；没有向真实 QQ、Hermes Gateway、Cron 或外部采集服务发送消息，也没有修改目标 Hermes Profile。真实 QQ Adapter 的被动多段投递、平台限额和发送失败重试仍需在目标 Hermes 环境单独验收。

## 最终结论

代码现在提供了可审计的两步交接：生成命令返回本次 `qq_report_path`，读取命令按该路径返回完整 QQ 正文和连续消息。手动触发的 Hermes Skill 已明确使用这条链路，避免旧日报、硬编码日期、重新生成和重复推送；原有定时任务继续保持只生成和保存日报。
