# GitHub 认证与限流加固

## 背景与目标

Daily Intelligence 需要继续支持匿名 GitHub 公共 API 采集，同时避免 Token 出现在 URL、重定向请求、异常文本和运行数据中。本次只修改项目内 GitHub collector 与离线测试，不涉及 Hermes 配置、Gateway 启动、QQ Bot、凭据或运行数据目录。

## 核心修改

- `GitHubClient` 在实例初始化时通过 `daily_intelligence.config.load_project_settings` 读取项目根目录 `.env`；当前进程中的 `GITHUB_TOKEN` 优先，空值回退到匿名请求。
- `.env` 路径由 `config.py` 的源码位置解析，不依赖当前工作目录、Hermes Gateway 环境继承或 GitHub CLI；仓库只提交 `.env.example` 空模板。
- API URL 只接受 HTTPS `api.github.com`，默认 opener 拒绝重定向；响应最终地址再次校验。
- 固定 GitHub 请求头，Token 只放在 `Authorization: Bearer ...` 中；对外 HTTP、网络和限流错误只输出脱敏信息。
- 403/429、5xx 和暂时性网络错误使用显式最大重试次数（默认 2 次，硬上限 5 次）和单次等待上限（默认 30 秒）。支持数值或 HTTP-date `Retry-After`、`X-RateLimit-Reset`；secondary rate limit 信号立即停止重试，超过 cap 时记录 reset 时间和等待秒数后失败。
- 当前 `GitHubClient` 实例维护有限容量的 ETag/响应体内存缓存，304 返回缓存命中，不写入运行目录。
- 同一次 collection 内按仓库 `full_name` 复用 Release 元数据，避免重复 Release 请求并保持输出去重语义。

## 验证与边界

新增离线测试覆盖 `.env` 的引号/注释/CRLF/缺失文件解析、进程变量优先级、固定请求头、匿名回退、主机与重定向安全、Token 脱敏、401 提示、Retry-After/X-RateLimit-Reset、secondary rate limit、网络重试、ETag/304、Release 去重和既有 Trending/RSS 解析。测试使用 fake opener，不访问真实 GitHub、RSS、Hermes、QQ Bot 或 Gateway；真实 Token、Hermes 部署和生产运行行为仍未验证。
