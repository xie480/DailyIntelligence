"""Daily Intelligence 命令行入口和运行编排。"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable

from . import __version__
from .collectors.github import GitHubClient, GitHubCollector
from .collectors.rss import RSSCollector
from .config import (
    DEFAULT_DATA_DIR,
    DEFAULT_TIMEZONE,
    RuntimePaths,
    configure_logging,
    date_in_timezone,
    timezone_or_default,
)
from .database import Database
from .handoff import import_handoff
from .models import Item
from .profile import InterestProfileStore
from .recommendations import RecommendationEngine
from .report import DailyReportRenderer, save_report


DEFAULT_SOURCES = {
    "github": {
        "per_page": 20,
        "include_releases": True,
        "include_readme": True,
        "readme_limit": 15,
        "queries": [
            {
                "name": "AI Agent",
                "query": "topic:agent",
                "section": "github_hot",
            },
            {
                "name": "MCP Skills",
                "query": "topic:mcp",
                "section": "github_hot",
            },
            {
                "name": "Interesting Projects",
                "query": "stars:>1000",
                "window": "30d",
                "section": "github_interesting",
            },
        ],
    },
    "rss": {
        "window_hours": 24,
        "supplement_days": 7,
        "feeds": [
            {
                "name": "OpenAI News",
                "url": "https://openai.com/news/rss.xml",
                "category": "ai",
            },
            {
                "name": "Hugging Face Blog",
                "url": "https://huggingface.co/blog/feed.xml",
                "category": "ai",
            },
            {
                "name": "GitHub Blog",
                "url": "https://github.blog/feed/",
                "category": "software",
            },
        ],
    },
}


def _add_runtime_overrides(
    parser: argparse.ArgumentParser,
) -> None:
    """让子命令也能在命令名后覆盖运行目录、源配置和时区。"""
    parser.add_argument(
        "--data-dir",
        default=argparse.SUPPRESS,
        help="覆盖运行数据目录",
    )
    parser.add_argument(
        "--source-config",
        default=argparse.SUPPRESS,
        help="覆盖采集源 JSON 配置路径",
    )
    parser.add_argument(
        "--timezone",
        default=argparse.SUPPRESS,
        help="覆盖 IANA 时区",
    )


def build_parser() -> argparse.ArgumentParser:
    """构造包含所有 v1 命令的参数解析器。"""
    parser = argparse.ArgumentParser(
        prog="daily_intelligence",
        description="Daily Intelligence 轻量技术情报系统",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    parser.add_argument(
        "--data-dir",
        default=str(DEFAULT_DATA_DIR),
        help="运行数据目录，默认使用 E:\\\\HermesData\\\\daily-intelligence",
    )
    parser.add_argument(
        "--source-config",
        default=None,
        help="采集源 JSON 配置路径，默认读取运行目录中的 sources.json",
    )
    parser.add_argument(
        "--timezone",
        default=DEFAULT_TIMEZONE,
        help="日报和运行锁使用的 IANA 时区",
    )
    subparsers = parser.add_subparsers(
        dest="command",
        required=True,
    )

    init_parser = subparsers.add_parser(
        "init-db",
        help="初始化数据库、画像和默认采集配置",
    )
    _add_runtime_overrides(init_parser)

    github_parser = subparsers.add_parser(
        "collect-github",
        help="采集 GitHub 仓库和最新 Release",
    )
    _add_runtime_overrides(github_parser)
    github_parser.add_argument(
        "--no-releases",
        action="store_true",
        help="不请求仓库最新 Release",
    )

    rss_parser = subparsers.add_parser(
        "collect-rss",
        help="采集 RSS/Atom 新闻",
    )
    _add_runtime_overrides(rss_parser)

    handoff_parser = subparsers.add_parser(
        "import-handoff",
        help="导入 Hermes Web Search 和项目分析 JSON",
    )
    _add_runtime_overrides(handoff_parser)
    handoff_parser.add_argument(
        "--file",
        required=True,
        help="Hermes 生成的结构化交接 JSON",
    )

    recommend_parser = subparsers.add_parser(
        "recommend",
        help="获取待推荐内容",
    )
    _add_runtime_overrides(recommend_parser)
    recommend_parser.add_argument(
        "--limit",
        type=int,
        default=15,
    )
    recommend_parser.add_argument(
        "--type",
        choices=[
            "github",
            "news",
        ],
        default=None,
    )
    recommend_parser.add_argument(
        "--no-record",
        action="store_true",
        help="不写入推荐历史",
    )
    recommend_parser.add_argument(
        "--json",
        action="store_true",
        help="以 JSON 输出",
    )

    feedback_parser = subparsers.add_parser(
        "feedback",
        help="更新用户兴趣反馈",
    )
    _add_runtime_overrides(feedback_parser)
    feedback_parser.add_argument(
        "feedback_text",
    )
    feedback_parser.add_argument(
        "--target",
        default=None,
        help="反馈所指向的项目或仓库",
    )

    profile_parser = subparsers.add_parser(
        "profile",
        help="查看、关闭、开启或重置兴趣画像",
    )
    _add_runtime_overrides(profile_parser)
    profile_subparsers = profile_parser.add_subparsers(
        dest="profile_command",
        required=True,
    )
    show_parser = profile_subparsers.add_parser(
        "show",
    )
    _add_runtime_overrides(show_parser)
    show_parser.add_argument(
        "--json",
        action="store_true",
    )
    reset_parser = profile_subparsers.add_parser(
        "reset",
    )
    _add_runtime_overrides(reset_parser)
    enable_parser = profile_subparsers.add_parser(
        "enable",
    )
    _add_runtime_overrides(enable_parser)
    disable_parser = profile_subparsers.add_parser(
        "disable",
    )
    _add_runtime_overrides(disable_parser)

    report_parser = subparsers.add_parser(
        "report",
        help="生成并保存指定日期日报",
    )
    _add_runtime_overrides(report_parser)
    report_parser.add_argument(
        "--date",
        dest="report_date",
        default=None,
        help="YYYY-MM-DD，缺省使用当前日期",
    )
    report_parser.add_argument(
        "--limit",
        type=int,
        default=15,
    )
    report_parser.add_argument(
        "--no-record",
        action="store_true",
        help="不写入推荐历史",
    )

    dry_run_parser = subparsers.add_parser(
        "dry-run",
        help="使用内置样例生成日报，不访问网络或写入运行数据",
    )
    _add_runtime_overrides(dry_run_parser)
    return parser


def main(
    argv: list[str] | None = None,
) -> int:
    """解析参数并执行一个 CLI 子命令。"""
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return _dispatch(args)
    except KeyboardInterrupt:
        print(
            "操作已取消",
            file=sys.stderr,
        )
        return 130
    except Exception as error:
        print(
            f"执行失败：{error}",
            file=sys.stderr,
        )
        return 1


def _dispatch(
    args: argparse.Namespace,
) -> int:
    """把解析后的命令分派到对应处理函数。"""
    handlers = {
        "init-db": _init_database,
        "collect-github": _collect_github,
        "collect-rss": _collect_rss,
        "import-handoff": _import_handoff,
        "recommend": _recommend,
        "feedback": _feedback,
        "profile": _profile,
        "report": _report,
        "dry-run": _dry_run,
    }
    return handlers[args.command](args)


def _runtime(
    args: argparse.Namespace,
) -> tuple[RuntimePaths, Database, InterestProfileStore]:
    """创建已初始化的运行路径、数据库和画像存储。"""
    paths = RuntimePaths.from_data_dir(args.data_dir)
    paths.ensure()
    configure_logging(paths)
    database = Database(paths.database_path)
    database.initialize()
    profile = InterestProfileStore(
        paths,
        database,
    )
    profile.load()
    return paths, database, profile


def _load_sources(
    args: argparse.Namespace,
    paths: RuntimePaths,
) -> dict[str, Any]:
    """读取运行目录或命令行指定的采集源配置。"""
    source_path = Path(
        args.source_config
        or paths.sources_path
    )
    if not source_path.is_file():
        return json.loads(
            json.dumps(
                DEFAULT_SOURCES,
                ensure_ascii=False,
            )
        )
    return json.loads(
        source_path.read_text(
            encoding="utf-8"
        )
    )


GITHUB_WINDOW_DAYS = {
    "24h": 1,
    "7d": 7,
    "30d": 30,
}


def _resolve_github_queries(
    queries: list[dict[str, Any]] | None,
    logical_date: date,
) -> list[dict[str, Any]]:
    """按逻辑日期展开 GitHub 查询的动态 pushed 时间窗口。"""
    resolved: list[dict[str, Any]] = []
    for query_config in queries or []:
        current = dict(query_config)
        window_days = current.get("window_days")
        if window_days is None:
            window = str(
                current.get("window")
                or ""
            ).casefold()
            window_days = GITHUB_WINDOW_DAYS.get(
                window,
            )
        try:
            window_days = int(window_days)
        except (
            TypeError,
            ValueError,
        ):
            window_days = 0
        query = str(
            current.get("query")
            or current.get("name")
            or "github"
        )
        if window_days > 0:
            cutoff = (
                logical_date
                - timedelta(days=window_days)
            ).isoformat()
            qualifier = f"pushed:>{cutoff}"
            query = re.sub(
                r"\bpushed:>\S+",
                qualifier,
                query,
            )
            if qualifier not in query:
                query = f"{query} {qualifier}"
            current["query"] = query
        resolved.append(current)
    return resolved


def _rss_failure_summary(
    failures: Iterable[Any],
) -> str:
    """拼接 Feed 失败来源和脱敏原因，避免写入响应正文。"""
    return "；".join(
        f"{failure.source} ({failure.reason})"
        for failure in failures
    )


def _init_database(
    args: argparse.Namespace,
) -> int:
    """初始化数据库、画像和运行配置。"""
    paths, database, profile = _runtime(args)
    try:
        if not paths.sources_path.is_file():
            paths.sources_path.write_text(
                json.dumps(
                    DEFAULT_SOURCES,
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
        profile.load()
        print(f"数据库已初始化：{paths.database_path}")
        return 0
    finally:
        database.close()


def _collect_github(
    args: argparse.Namespace,
) -> int:
    """执行一次 GitHub 采集并保存 Star 快照。"""
    paths, database, _ = _runtime(args)
    current = datetime.now(
        timezone_or_default(args.timezone),
    )
    logical_date = _run_date(
        args,
        now=current,
    )
    run_key = f"github:{logical_date.isoformat()}"
    if not database.begin_run(
        "github",
        run_key,
    ):
        database.close()
        print("今日 GitHub 采集已完成或正在运行")
        return 0
    try:
        config = _load_sources(
            args,
            paths,
        ).get("github") or {}
        client = GitHubClient()
        if client.token is None:
            print(
                "未找到 GITHUB_TOKEN，使用匿名 GitHub API，配额较低。",
                file=sys.stderr,
            )
        items = GitHubCollector(client).collect(
            queries=_resolve_github_queries(
                config.get("queries"),
                logical_date,
            ),
            per_page=int(config.get("per_page") or 20),
            include_releases=not args.no_releases
            and bool(config.get("include_releases", True)),
            enrich_readme=bool(config.get("include_readme", True)),
            readme_limit=int(config.get("readme_limit") or 15),
        )
        snapshot_date = GitHubCollector.snapshot_date(
            args.timezone,
            now=current,
        )
        for item in items:
            database.upsert_item(item)
            if item.repo_full_name:
                database.save_repo_snapshot(
                    item.repo_full_name,
                    snapshot_date,
                    int(item.stars or 0),
                    int(item.forks or 0),
                )
        database.finish_run(
            run_key,
            "success",
        )
        print(f"GitHub 采集完成：{len(items)} 条")
        return 0
    except Exception as error:
        database.finish_run(
            run_key,
            "failed",
            str(error),
        )
        print(
            f"GitHub 采集失败：{error}",
            file=sys.stderr,
        )
        return 1
    finally:
        database.close()


def _collect_rss(
    args: argparse.Namespace,
) -> int:
    """执行一次 RSS/Atom 采集并保存项目。"""
    paths, database, _ = _runtime(args)
    current = datetime.now(
        timezone_or_default(args.timezone),
    )
    logical_date = _run_date(
        args,
        now=current,
    )
    run_key = f"rss:{logical_date.isoformat()}"
    if not database.begin_run(
        "rss",
        run_key,
    ):
        database.close()
        print("今日 RSS 采集已完成或正在运行")
        return 0
    try:
        config = _load_sources(
            args,
            paths,
        ).get("rss") or {}
        collection = RSSCollector().collect_with_report(
            feeds=config.get("feeds") or [],
            now=current,
            window_hours=int(config.get("window_hours") or 24),
            supplement_days=int(config.get("supplement_days") or 7),
        )
        items = collection.items
        for item in items:
            database.upsert_item(item)
        if collection.failures and not collection.successful_feeds:
            error = _rss_failure_summary(
                collection.failures,
            )
            database.finish_run(
                run_key,
                "failed",
                error,
            )
            print(
                f"RSS 采集失败：{error}",
                file=sys.stderr,
            )
            return 1
        if collection.failures:
            error = _rss_failure_summary(
                collection.failures,
            )
            database.finish_run(
                run_key,
                "partial",
                error,
            )
            print(
                "RSS 采集完成："
                f"{len(items)} 条，成功 {collection.success_count} 个 Feed，"
                f"失败 {collection.failure_count} 个 Feed",
            )
            print(
                f"RSS 失败来源：{error}",
                file=sys.stderr,
            )
            return 0
        database.finish_run(
            run_key,
            "success",
        )
        print(
            f"RSS 采集完成：{len(items)} 条，"
            f"成功 {collection.success_count} 个 Feed，失败 0 个 Feed"
        )
        return 0
    except Exception as error:
        database.finish_run(
            run_key,
            "failed",
            str(error),
        )
        print(
            f"RSS 采集失败：{error}",
            file=sys.stderr,
        )
        return 1
    finally:
        database.close()


def _import_handoff(
    args: argparse.Namespace,
) -> int:
    """导入 Hermes 搜索结果并记录独立的 Web Search 运行状态。"""
    paths, database, _ = _runtime(args)
    current = datetime.now(
        timezone_or_default(args.timezone),
    )
    logical_date = _run_date(
        args,
        now=current,
    )
    run_key = f"web-search:{logical_date.isoformat()}"
    if not database.begin_run(
        "web_search",
        run_key,
    ):
        database.close()
        print("今日 Web Search 交接已完成或正在运行")
        return 0
    try:
        result = import_handoff(
            database,
            args.file,
            paths.handoff_path,
        )
        database.finish_run(
            run_key,
            "success",
        )
        print(
            "Web Search 交接完成："
            f"导入 {result['news_imported']} 条新闻，"
            f"更新 {result['projects_updated']} 个项目"
        )
        return 0
    except Exception as error:
        database.finish_run(
            run_key,
            "failed",
            str(error),
        )
        print(
            f"Web Search 交接失败：{error}",
            file=sys.stderr,
        )
        return 1
    finally:
        database.close()


def _recommend(
    args: argparse.Namespace,
) -> int:
    """输出推荐结果。"""
    paths, database, profile = _runtime(args)
    try:
        results = RecommendationEngine(
            database,
            profile,
        ).recommend(
            limit=args.limit,
            item_type=args.type,
            record=not args.no_record,
        )
        if args.json:
            print(
                json.dumps(
                    results,
                    ensure_ascii=False,
                    indent=2,
                )
            )
        else:
            for index, item in enumerate(
                results,
                1,
            ):
                print(
                    f"{index}. {item['title']} "
                    f"({item['recommendation_score']:.2f})"
                )
                print(
                    f"   {item['match_reason']} | {item['url']}"
                )
        return 0
    finally:
        database.close()


def _feedback(
    args: argparse.Namespace,
) -> int:
    """保存一条自然语言兴趣反馈。"""
    paths, database, profile = _runtime(args)
    try:
        result = profile.apply_feedback(
            args.feedback_text,
            target=args.target,
        )
        print(result.message)
        return 0
    finally:
        database.close()


def _profile(
    args: argparse.Namespace,
) -> int:
    """处理画像查看、开启、关闭和重置命令。"""
    _, database, profile = _runtime(args)
    try:
        if args.profile_command == "show":
            value = profile.load()
            print(
                json.dumps(
                    value,
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0
        if args.profile_command == "reset":
            profile.reset()
            print("兴趣画像已重置")
            return 0
        enabled = args.profile_command == "enable"
        profile.set_enabled(enabled)
        print(
            "兴趣画像已开启"
            if enabled
            else "兴趣画像已关闭"
        )
        return 0
    finally:
        database.close()


def _report(
    args: argparse.Namespace,
) -> int:
    """生成、保存并打印指定日期的日报路径。"""
    paths, database, profile = _runtime(args)
    try:
        report_date = (
            date.fromisoformat(args.report_date)
            if args.report_date
            else _run_date(args)
        )
        renderer = DailyReportRenderer()
        engine = RecommendationEngine(
            database,
            profile,
        )
        results = engine.recommend(
            limit=args.limit,
            record=False,
        )
        rendered_results = renderer.select_rendered_items(
            results,
            total_limit=args.limit,
        )
        markdown = renderer.render(
            results,
            report_date=report_date,
            total_limit=args.limit,
        )
        report_path = save_report(
            paths,
            markdown,
            report_date,
        )
        if not args.no_record:
            engine.record_recommendations(
                rendered_results,
                report_date=report_date,
            )
        print(f"日报已保存：{report_path}")
        return 0
    finally:
        database.close()


def _dry_run(
    args: argparse.Namespace,
) -> int:
    """使用固定样例验证日报渲染，不创建运行数据。"""
    report = DailyReportRenderer().render(
        [
            asdict(
                Item(
                    item_type="github",
                    title="example/agent-tool",
                    url="https://github.com/example/agent-tool",
                    source="Dry Run",
                    summary="用于演示的 Agent 工具。",
                    category="AI Agent",
                    metadata={
                        "section": "github_hot",
                    },
                )
            ),
            asdict(
                Item(
                    item_type="news",
                    title="Example Agent News",
                    url="https://example.com/agent-news",
                    source="Dry Run",
                    summary="用于演示的 Agent 新闻。",
                    category="agent",
                )
            ),
        ],
        report_date=_run_date(args),
    )
    print(report)
    return 0


def _run_date(
    args: argparse.Namespace,
    now: datetime | None = None,
) -> date:
    """根据命令行时区计算采集运行日期。"""
    return date_in_timezone(
        args.timezone,
        now,
    )


if __name__ == "__main__":
    raise SystemExit(main())

