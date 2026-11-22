# GitHub 项目级代理配置

## 背景与目标

Windows PowerShell、Codex 和 Hermes 子进程可能解析到不同的通用代理。Daily Intelligence 通过项目 `.env` 的 `GITHUB_PROXY` 为 GitHub API 提供独立代理配置，避免错误的 `HTTP_PROXY`、`HTTPS_PROXY` 或 `ALL_PROXY` 影响 GitHub 请求。

## 配置与优先级

`GitHubClient` 复用 `daily_intelligence.config.load_project_settings`，优先级如下：

1. 进程级 `GITHUB_PROXY`。
2. 项目根目录 `.env` 的 `GITHUB_PROXY`。
3. Python 自动代理发现。

显式代理同时映射到 HTTP 和 HTTPS 请求，并覆盖通用代理变量。代理地址只支持 `http://` 或 `https://`，校验主机名、端口、路径、查询参数和片段。用户名和密码可以由 urllib 使用，但不会进入日志或错误文本。

显式代理与 `NO_PROXY` 对 `api.github.com` 发生冲突时，客户端直接抛出脱敏配置错误，避免自动绕过后直连。客户端使用实例级 `ProxyHandler` 和 `OpenerDirector`，不调用 `install_opener()`，不修改 `os.environ`，也不影响 RSS 或其他 HTTP 客户端。

## 核心修改

- `daily_intelligence/config.py` 保存项目变量和进程变量来源，提供 `github_proxy` 与 `github_proxy_source`。
- `daily_intelligence/collectors/github.py` 创建 GitHub 专用 opener，保留 Token 认证、ETag、限流重试、TLS 校验和网络错误分类。
- `.env` 仅新增或更新 `GITHUB_PROXY=http://127.0.0.1:7890`；原有 Token 与其他配置保持不变。
- `.env.example` 提供代理示例地址，部署时按本机代理客户端监听端口调整。

## 离线验证

新增测试覆盖项目文件读取、进程优先级、通用代理覆盖、自动代理回退、无效地址、`NO_PROXY` 冲突、全局 opener/环境变量隔离及 Token/代理凭据脱敏。所有测试使用 Mock，不消耗 GitHub API 额度。

本轮执行 `python -m unittest discover -s tests -v`，71 个测试全部通过；`python -m compileall -q daily_intelligence tests` 和 `python -m daily_intelligence --version` 也通过。实际项目配置的脱敏检查结果为 `token_loaded=yes`、`proxy_mode=explicit`、`proxy_source=project_env`、`proxy_scheme=http`、`proxy_port=7890`。

真实验证命令见项目交付报告；执行时只读取 `/rate_limit` 和最多两条 Repository Search，不创建 SQLite、日报或缓存文件。

## Windows PowerShell 真实集成命令

在项目目录执行以下命令。脚本通过 `environ={}` 强制使用项目 `.env`，只打印认证状态、代理安全元数据、额度和仓库公开字段，不打印 Token、Authorization 或代理凭据：

~~~~powershell
Set-Location "E:\YilenaCode\DailyIntelligence"
@'
from pathlib import Path

from daily_intelligence.collectors.github import (
    GitHubAPIError,
    GitHubClient,
    GitHubNetworkError,
)
from daily_intelligence.config import load_project_settings

root = Path.cwd()
settings = load_project_settings(root, environ={})
client = GitHubClient(
    project_root=root,
    environ={},
    retries=0,
)
print(
    "client="
    f"token_loaded={'yes' if settings.github_token else 'no'} "
    f"proxy_mode={client.proxy_mode} "
    f"proxy_source={client.proxy_source} "
    f"proxy_scheme={client.proxy_scheme or 'auto'} "
    f"proxy_port={client.proxy_port or 'auto'}"
)

try:
    rate = client.get_json("/rate_limit")
    resources = rate["resources"]
    print(
        "rate_limit=ok "
        f"core_remaining={resources['core']['remaining']} "
        f"search_remaining={resources['search']['remaining']}"
    )
    result = client.get_json(
        "/search/repositories"
        "?q=topic%3Aagent+language%3APython"
        "&sort=stars&order=desc&per_page=2"
    )
    items = result.get("items") or []
    print(
        "repository_search=ok "
        f"total_count={result.get('total_count')} "
        f"returned={len(items)}"
    )
    for index, item in enumerate(items[:2], start=1):
        description = " ".join(
            str(item.get("description") or "").split()
        )
        if client.token:
            description = description.replace(
                client.token,
                "[REDACTED]",
            )
        print(
            f"repository_{index}="
            f"name={item.get('full_name')} "
            f"description={description[:160]!r} "
            f"stars={item.get('stargazers_count')} "
            f"url={item.get('html_url')}"
        )
except GitHubNetworkError as error:
    print(
        "github=network_error "
        f"category={error.category} "
        f"reason_type={error.reason_type} "
        f"proxy={'configured' if error.proxy_configured else 'not-configured'}"
    )
    raise SystemExit(1)
except GitHubAPIError as error:
    print(f"github=http_error code={error.code}")
    raise SystemExit(1)
except Exception as error:
    print(f"github=unexpected_error type={type(error).__name__}")
    raise SystemExit(1)
'@ | python -
~~~~

## 风险与边界

- 代理服务不可用时，GitHubClient 会报告 `proxy` 类网络错误并停止，不会静默直连。
- 本配置不改变 Windows 系统代理、Hermes Gateway、RSS 请求或其他 Python 客户端。
- 真实 GitHub、Hermes、Cron、QQ Bot 端到端行为仍需在目标运行环境分别验收。
