---
name: dailyintelligence-creators
description: 通过 Hermes QQ Bot 管理 Daily Intelligence 的 Bilibili UP 主和 YouTube 频道监控账号。
version: 1.0.0
author: Daily Intelligence
license: MIT
platforms: [windows, linux, macos]
metadata:
  hermes:
    tags: [daily-intelligence, creators, bilibili, youtube, monitoring]
    category: research
    related_skills: [daily-intelligence-local]
---

# DailyIntelligence Creators

## 适用范围

本 Skill 只处理 Daily Intelligence 的创作者监控账号管理：识别主页链接、添加账号、查看列表、删除账号、暂停/恢复账号，以及修改视频/动态监控类型。用户可以使用“关注这个 UP 主”“添加这个 YouTube 频道”“查看我关注的创作者”“暂停/恢复”“只监控视频”等自然语言表达。

本 Skill 不负责以下事项：

- 不负责实际采集视频和动态。
- 不负责生成日报。
- 不负责启动后台监控服务。
- 不负责创建 Cron 任务。
- 不负责修改 DailyIntelligence 的采集时间窗口。
- 不负责修改 Hermes QQ Bot 配置。
- 不修改 Hermes Profile。
- 不将账号数据写入 Hermes Memory。
- 不直接操作 SQLite，也不拼接或执行 SQL。
- 不虚报操作成功；必须等 Backend 返回并校验结构化结果。

日报查询、采集、推荐和报告编排仍由 `daily-intelligence-local` 负责。本 Skill 不应与这些请求混用。

## 受信任的运行上下文

所有管理操作都必须绑定当前 QQ 私聊的稳定 sender ID。sender ID 只能从 Hermes 入站上下文取得，不能接受用户在消息正文中自报的 owner，也不能由模型猜测或改写。Hermes 必须同时提供安装环境配置的 Daily Intelligence 项目目录和运行数据目录；本 Skill 不写死任何数据库路径、凭据或运行目录。

使用 Hermes 已确认的 `terminal` 工具，在项目目录中执行 Python CLI。下面的命令模板中的 `<DAILY_INTELLIGENCE_PROJECT_ROOT>`、`<DAILY_INTELLIGENCE_DATA_DIR>` 和 `<TRUSTED_SENDER_ID>` 都是可信运行时参数，不是让用户填写的文本。调用时应把可执行文件和参数作为独立参数传给 `terminal`，或使用该工具提供的安全参数转义方式；禁止把用户输入拼接成可执行的 Shell 字符串，禁止使用 `Invoke-Expression`、`cmd /c` 拼接或等价方式。

完整命令、JSON 字段和错误码见 `references/commands.md`。所有命令都要带 `creator --json`，以便区分成功、失败和 Backend 返回的实际状态。

## 平台识别和添加流程

### Bilibili UP 主

只把 `https://space.bilibili.com/<数字 UID>`（也接受同域名的 `www` 形式）识别为 Bilibili 空间链接。不要把视频链接或搜索结果当作 UP 主主页。

收到“关注/添加”意图和有效链接后，按以下顺序处理：

1. 调用 `creator --json add`，由 Backend 解析 UID 并尝试读取 UP 主名称。
2. Backend 检查同平台重复账号；返回 `CREATOR_ALREADY_EXISTS` 时告知账号已存在，不再次添加。
3. 不传 `--no-videos` 或 `--no-dynamics`，默认启用视频和动态监控。直播监控不支持，也不要给用户承诺直播通知。
4. 仅在 JSON 中 `ok: true` 且包含实际 `creator` 后，反馈名称、UID、主页链接和监控状态。

### YouTube 频道

识别以下两种频道主页：

- `https://www.youtube.com/@<handle>`
- `https://www.youtube.com/channel/UC...`

`@handle` 由 Backend 解析为真实 Channel ID；解析失败时返回错误，不写入猜测的账号。YouTube 只支持新视频监控，不支持动态、社区帖子或直播。添加时不传 `--no-videos`，也不传 `--no-dynamics`。

### 添加失败处理

每次添加都要等待命令结束，并同时检查退出码、标准输出是否为合法 JSON、`ok` 是否为 `true`。非零退出码、JSON 解析失败、`ok: false`、名称/Channel ID 解析失败或 Backend 异常，都必须反馈失败原因；不得根据“命令已发出”或旧列表推断成功。

## 查看监控列表

调用 `creator --json list`，只显示当前可信 sender ID 所属账号。按 Bilibili、YouTube 分组，至少展示：

- 平台。
- 创作者名称。
- 账号主页链接。
- `active` 或 `paused` 状态。
- 已启用的监控类型（Bilibili 可为视频/动态，YouTube 仅视频）。
- `created_at` 添加时间。

暂停账号也要保留在列表中，并明确显示为已暂停。没有账号时直接说明当前列表为空。

## 定位、删除、暂停和恢复

删除、暂停和恢复都必须先读取列表，再把用户给出的名称或链接映射为精确的 `platform + account_key`。删除前必须确认：

1. 优先匹配规范化主页链接和账号键，再匹配完整创作者名称。
2. 零个匹配时要求用户提供有效主页链接或更明确的名称，不执行变更。
3. 多个匹配时列出平台、名称、链接和状态，要求用户选择具体目标；在选择前不执行变更。
4. 删除是破坏性操作，单个匹配也必须先向用户展示目标并请求明确确认。没有确认时不调用删除命令。

确认后调用引用文件中的精确命令，并等待结构化结果：

- 删除：`remove` 成功后只报告 Backend 返回的 `removed` 目标；不要把删除描述成暂停。
- 暂停：调用 `pause`，保留账号历史数据、事件和检查点。
- 恢复：调用 `resume`，Backend 会继续使用该账号保存的有效检查点；暂停期间的所有历史内容不会被 Skill 主动无条件灌入日报。

如果返回 `CREATOR_NOT_FOUND`，说明列表与 Backend 状态发生变化，应重新读取列表后再让用户选择，不能重复猜测账号键。

## 修改监控类型

修改前必须读取当前账号，合并用户要求和未改变的设置，再调用 `configure`，避免把未提及的监控类型意外关闭：

- Bilibili 支持视频和动态两个开关。`--no-videos` 关闭视频，`--no-dynamics` 关闭动态；未传对应开关表示开启。
- YouTube 只支持视频。对 YouTube 请求开启动态时直接说明不支持，不调用 Backend；关闭视频时使用 `--no-videos`。
- 不提供直播监控参数，也不创建实时通知任务。

只有返回 `ok: true` 且 `creator.monitor_videos`/`creator.monitor_dynamics` 与目标设置一致时，才反馈“监控类型已更新”。

## 权限和错误码

Backend 使用 `--owner-key` 校验账号归属和授权表。当前项目支持 `CREATOR_ADMIN_KEYS` 预置白名单；没有预置授权时，Backend 只在授权表为空时原子登记首个可信 sender ID，后续其他 sender 不会自动获得权限。若 Hermes 无法提供稳定、可信的 sender ID，应停止管理操作并明确记录集成缺口，不能假设所有 QQ 消息发送者都是管理员。

Skill 至少按以下错误码处理：

| 错误码 | 处理 |
| --- | --- |
| `CREATOR_ALREADY_EXISTS` | 告知已存在，保留现有设置 |
| `CREATOR_UNAUTHORIZED` | 拒绝操作，不尝试替换 owner key |
| `CREATOR_NOT_FOUND` | 重新读取列表，请用户重新选择 |
| `INVALID_CREATOR_URL` | 说明只接受 Bilibili 空间或 YouTube 频道主页 |
| `CREATOR_UNSUPPORTED_MONITORING` | 说明 YouTube 不支持动态/直播 |
| `CREATOR_BACKEND_ERROR` | 报告实际失败阶段，不虚报成功 |

任何未知错误码、非零退出码或无效 JSON 都按失败处理，并保留 Backend 的安全错误信息。不要把数据库路径、Cookie、Token 或完整聊天记录回显给用户。

## 与 Hermes 的边界

本目录是 Skill 源文件，只供 Hermes 后续安装和审阅。本次开发不安装 Skill，不复制到 Hermes 实际运行目录，不修改任何 Hermes Profile，不修改 `skills.external_dirs`，不创建 Cron，不重启 Gateway，也不发送真实 QQ 消息。安装时由 Hermes 按目标版本校验 Skill frontmatter、`terminal` 工具参数、项目目录和运行数据目录。
