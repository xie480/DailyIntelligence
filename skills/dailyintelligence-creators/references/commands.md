# dailyintelligence-creators Backend 命令契约

本文档只记录 Skill 调用现有 Daily Intelligence CLI 的参数和 JSON 契约。`<DAILY_INTELLIGENCE_PROJECT_ROOT>`、`<DAILY_INTELLIGENCE_DATA_DIR>`、`<TRUSTED_SENDER_ID>` 和 `<ACCOUNT_KEY>` 是调用方在受信任上下文中解析出的参数，不是用户输入模板，也不是固定路径或凭据。

## 调用方式

使用 Hermes 已提供的 `terminal` 工具，在 `<DAILY_INTELLIGENCE_PROJECT_ROOT>` 工作目录执行：

```text
python -m daily_intelligence --data-dir <DAILY_INTELLIGENCE_DATA_DIR> creator --json <subcommand> ... --owner-key <TRUSTED_SENDER_ID>
```

参数必须作为独立参数传递并安全转义。不要拼接用户消息成 Shell 命令，不要把 `<DAILY_INTELLIGENCE_DATA_DIR>` 替换为 Skill 中的硬编码路径，不要把 owner key、Cookie 或 Token 写入命令模板。

## 命令

### 添加

```text
python -m daily_intelligence --data-dir <DAILY_INTELLIGENCE_DATA_DIR> creator --json add --owner-key <TRUSTED_SENDER_ID> <CREATOR_URL>
```

一次只传一个 URL，便于把每个 Backend 结果准确反馈给用户。Bilibili 默认 `monitor_videos=true`、`monitor_dynamics=true`；YouTube 默认 `monitor_videos=true`、`monitor_dynamics=false`。

### 列表

```text
python -m daily_intelligence --data-dir <DAILY_INTELLIGENCE_DATA_DIR> creator --json list --owner-key <TRUSTED_SENDER_ID>
```

### 删除、暂停和恢复

这些命令只接受经过列表匹配得到的精确平台和账号键：

```text
python -m daily_intelligence --data-dir <DAILY_INTELLIGENCE_DATA_DIR> creator --json remove <PLATFORM> <ACCOUNT_KEY> --owner-key <TRUSTED_SENDER_ID>
python -m daily_intelligence --data-dir <DAILY_INTELLIGENCE_DATA_DIR> creator --json pause <PLATFORM> <ACCOUNT_KEY> --owner-key <TRUSTED_SENDER_ID>
python -m daily_intelligence --data-dir <DAILY_INTELLIGENCE_DATA_DIR> creator --json resume <PLATFORM> <ACCOUNT_KEY> --owner-key <TRUSTED_SENDER_ID>
```

`<PLATFORM>` 只能是 `bilibili` 或 `youtube`。删除前必须在自然语言交互中取得明确确认。

### 修改监控类型

```text
python -m daily_intelligence --data-dir <DAILY_INTELLIGENCE_DATA_DIR> creator --json configure <PLATFORM> <ACCOUNT_KEY> --owner-key <TRUSTED_SENDER_ID> [--no-videos] [--no-dynamics]
```

`configure` 是完整设置，不是单字段 toggle：Skill 应先读取当前账号，再为未改变的设置补齐开关。YouTube 的动态值由 Backend 固定为关闭；不要对 YouTube 传入开启动态的意图。

## 成功响应

所有 `--json` 成功命令退出码为 `0`，输出合法 JSON 且 `ok` 为 `true`。添加单个账号时包含 `creator` 和 `creators`；列表包含 `creators`；暂停、恢复和配置包含更新后的 `creator`；删除包含 `removed`：

```json
{
  "ok": true,
  "action": "add_creator",
  "creator": {
    "id": 123,
    "platform": "bilibili",
    "account_key": "123456",
    "display_name": "示例 UP 主",
    "profile_url": "https://space.bilibili.com/123456",
    "status": "active",
    "monitor_videos": true,
    "monitor_dynamics": true,
    "created_at": "2026-11-22T12:00:00+00:00"
  },
  "creators": []
}
```

上例中的 `id`、名称和时间只是字段示例，Skill 必须展示 Backend 实际返回值，不得照抄示例。

## 失败响应

失败命令退出码为 `1`，输出合法 JSON 且 `ok` 为 `false`。Skill 必须同时检查退出码和 `ok`，不能只看标准输出是否存在：

```json
{
  "ok": false,
  "action": "add_creator",
  "error_code": "CREATOR_ALREADY_EXISTS",
  "message": "同平台账号已经存在"
}
```

当前稳定错误码包括：`CREATOR_ALREADY_EXISTS`、`CREATOR_UNAUTHORIZED`、`CREATOR_NOT_FOUND`、`INVALID_CREATOR_URL`、`CREATOR_UNSUPPORTED_MONITORING`、`CREATOR_INVALID_REQUEST` 和 `CREATOR_BACKEND_ERROR`。未知错误码、非零退出码、空输出或非法 JSON 都必须按失败处理。

## 数据和权限边界

- CLI 复用 `CreatorAccountService`、`creator_urls` 和现有 SQLite 事务；Skill 不直接操作数据库。
- `--owner-key` 必须是 Hermes 入站上下文中的可信 sender ID，不能来自用户消息正文。
- CLI 只返回当前 owner 的账号；Backend 负责授权、账号归属、重复检查和状态持久化。
- Skill 不读取或写入 Hermes Memory，不存储完整 QQ 聊天记录，不回显 Token/Cookie，不创建采集进程或 Cron。
