# 第二轮上线阻塞修复

## 背景与目标

本轮针对 Windows 测试目录权限、GitHub 网络诊断、Hermes Skill 同名冲突、时区一致性、RSS 单源失败、日报落盘一致性和 GitHub 动态查询窗口进行最小修改，为下一轮 Hermes 端到端验收准备可重复的本地证据。

## 根因与修复

### Windows 测试目录

原测试在项目根目录固定创建 `.test-tmp/<uuid>`，Windows ACL 错误会在 `setUp` 和清理阶段放大为大量错误。测试现在通过 `tests/test_support.py` 优先使用 `tempfile.TemporaryDirectory`；若受限沙箱拒绝系统临时目录，则使用项目根目录下随机名称目录作为回退。每个测试独立创建并自动清理，不使用真实运行数据、SQLite 或历史日报。

### GitHub 网络诊断

`GitHubClient` 以前只记录 `URLError` 类型，无法区分底层原因。现在读取 `URLError.reason` 的类型，脱敏记录 DNS、timeout、TLS、proxy、connection 或 network 类别，并保留 `reason_type` 和代理是否配置状态。默认 opener 在请求时按当前代理环境创建，仍使用标准库 TLS 校验和禁止重定向，不修改系统代理或 VPN。

当前环境的单次只读 `/rate_limit` 请求结果为：`category=proxy`、`reason_type=ConnectionRefusedError`、`proxy=configured`。HTTP/HTTPS/ALL_PROXY 均存在，`api.github.com` 不在 `NO_PROXY`；因此本轮已定位到代理连接被拒绝，未判定为 GitHub API 或 Token 失效。未输出 Token、代理 URL 或请求头。

### Skill 名称

本地调度 Skill 已移动到：

`E:\YilenaCode\DailyIntelligence\skills\daily-intelligence-local`

元数据名称、README、部署文档、任务计划和三个关联 Skill 已同步。`github-radar`、`tech-news-radar`、`interest-profile` 保留不变。Hermes CLI 在当前环境因 `E:\HermesData\installs\...\.install.lock` 不可写而无法执行帮助命令；因此未声称绝对路径参数得到 Hermes 运行时支持。文档明确使用项目 `skills` 外部目录和唯一的 `daily-intelligence-local` 名称，并要求按目标 Profile 实际命令验证。

### 时区与动态窗口

新增可注入的 `date_in_timezone`/`now_in_timezone`，CLI 运行日期、GitHub Star 快照、日报默认日期统一使用 `Asia/Shanghai`，仍支持显式 IANA 时区。GitHub 查询支持 `24h`、`7d` 和 `30d` 窗口，按逻辑日期动态生成 `pushed:>` 条件；默认有趣项目查询不再包含固定历史日期。

### RSS 与日报一致性

RSS 新增批次结果，逐个 Feed 隔离异常，有限重试只用于网络错误，HTTP 永久错误不重试；CLI 输出成功/失败 Feed 数量，并将部分成功记录为 `partial`。日报现在先原子保存文件，再以 SQLite 批量事务写推荐历史。文件保存失败不会留下推荐历史；历史写入失败时文件可保留，重复执行会幂等补齐。报告临时文件使用随机名称、`fsync` 和原子替换。

## 验证

- `python -m unittest discover -s tests -v`：本轮完整套件 62 个测试通过。
- `python -m compileall -q daily_intelligence tests`：通过。
- `git diff --check`：通过。
- Mock 覆盖 GitHub DNS、超时、TLS、代理、HTTP 限流和 Token 脱敏；未用真实请求消耗额度。
- 单独真实只读请求已记录上述代理连接诊断；未声称 GitHub、RSS、Hermes Cron 或 QQ Bot 端到端通过。

## 未验证边界

- 当前 Hermes CLI 无法读取帮助，未修改 Hermes 配置，也未确认目标 Profile 的实际 `skills.external_dirs` serving 状态。
- 代理修复需要由部署环境管理员检查代理服务或 `NO_PROXY`，本项目不修改系统网络配置。
- 真实 RSS、Cron、QQ Bot 和 Hermes Skill 端到端行为仍需下一轮在目标环境分层验收。
