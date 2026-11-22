# Acceptance and Hermes Integration

## When to Use

Use this reference when auditing a Daily Intelligence release, wiring its local Skills into Hermes, validating Cron execution, or preparing a QQ Bot dry-run without sending a real message.

## Evidence levels

Treat these as separate claims and report them separately:

| Level | What it proves | What it does not prove |
|---|---|---|
| Static inspection | Code paths, configuration, schema, Skill text and safety boundaries exist | Runtime behavior, network access or message delivery |
| Unit/mock test | Local logic under controlled inputs | Real GitHub/RSS responses, Hermes Cron or QQ Bot |
| Disposable smoke test | CLI wiring, rendering, SQLite behavior and idempotency in isolated data | Production database safety, gateway routing or external delivery |
| Real read-only API test | Endpoint reachability, redacted auth status and quota data | Inbound QQ handling or scheduled execution |
| Hermes Cron run | Scheduler, workdir, Skill selection and local delivery path | QQ passive reply unless a real inbound message is exercised |
| QQ dry-run/preview | Message formatting, chunking and intended target | Successful external delivery |
| Real QQ test | Actual inbound/outbound adapter behavior | Broad project correctness outside the exercised path |

Never collapse these levels into a single “integration passed” result.

## Read-only preflight

1. Resolve the serving profile with `hermes profile list`, `hermes profile show <profile>`, `hermes status --full`, and `hermes gateway status --deep --full`.
2. Read `hermes config get skills.external_dirs --json` and preserve every existing directory before any proposed change.
3. Confirm the repository Skill with `hermes skills list --source local --enabled-only -p <profile>`. When a local Skill and a hub Skill share a name, treat bare `hermes skills inspect <name>` as ambiguous; verify the exact local source path and use a no-write dry-run.
4. Inspect `hermes cron list`, `hermes cron status`, `hermes cron doctor`, `hermes cron runs`, and `hermes cron incidents`. Confirm explicit `workdir`, IANA timezone, required Skills, and `local` delivery for report-generation jobs.
5. Keep project runtime data outside the source repository when configured that way. Never delete the existing database or historical reports to make a test pass.

## Cross-checking local Skills, Cron, and delivery

- Compare the exact Skill names in `hermes cron list`/the profile Cron job definition with `hermes skills list --source local --enabled-only -p <profile>`. A job can finish with scheduler status `ok` while referencing a stale bare name that is absent locally and resolves to a Hub candidate.
- Read the Cron output and the project's `runs` table after each acceptance run. `cron doctor` and a completed Agent response do not prove that GitHub, RSS, report persistence, or downstream delivery succeeded.
- Record `hermes send --list qqbot` before any delivery claim. “Configured” or a connected WebSocket proves transport/configuration only; an empty channel discovery and an unapproved target keep proactive delivery unverified.

## Safe API and CLI checks

- Load GitHub credentials through the project's own configuration path; for a controlled environment test use `load_project_settings(project_root, environ={})` and `GitHubClient(project_root=project_root, environ={}, retries=0)`. Never put a token in a command-line argument.
- Use only read endpoints for acceptance (`rate_limit`, repository search, repository metadata and release metadata). Report whether the client loaded a token and whether the request reached the API; never print secrets, headers or full environment variables. If generic `HTTP(S)_PROXY` values are injected for a precedence test, assert that the intended project-level proxy still wins without changing machine-wide settings.
- Run the canonical unit suite from a writable temporary location. If setup fails with an OS permission error, repair the test environment or choose another writable temp directory and rerun before judging assertions.
- Use a disposable data directory for CLI smoke tests. Run the same logical date twice for both `--no-record` and ordinary recording paths; compare report content/hash plus SQLite recommendation, run and collection side effects because item-level deduplication may still allow a recording rerun to select a new batch.
- Verify the report's logical date comes from the same explicit timezone used by collection and Cron. A local `date.today()` mixed with an explicit IANA timezone can cross a midnight boundary and label the report incorrectly.
- When the source configuration has no feed for a requested category, report collection success separately from section population; an empty Agent/AI/software section can come from source coverage, date windows, or ranking filters and must not be mislabeled as a transport failure.
- Do not call a report-generation command successful when it records recommendation history before the report file is durably saved; that ordering can leave database history without a deliverable report.

## QQ boundary

When QQ Bot is supplied by Hermes rather than project code, validate the layers independently:

1. project produces a source-backed report or message preview;
2. Hermes receives the user intent and selects the local Skill;
3. the adapter handles passive reply, message length/chunking, rate limits and deduplication;
4. proactive delivery is separately authorized with a confirmed target, schedule and timezone.

A configured QQ adapter, a connected WebSocket, or a successful local Cron run is not evidence that a real user message was answered or that proactive delivery works. Check channel discovery and the actual `hermes send` target path, then obtain approval for the target, schedule, timezone, and message preview before sending a real test message.

## Manual report response

For a user message such as “生成今天的日报”, the passive reply flow is separate from Cron delivery:

1. Run `report --json` once and require `ok: true`.
2. Read the returned `qq_report_path` with `read-report --path "<qq_report_path>" --json`.
3. Treat `content` and `messages` as the factual source only. Apply `references/report-polishing.md` to every message: remove Markdown presentation, translate explanatory English into natural Chinese, and keep links, statuses, numbers, chapters and item order unchanged.
4. Prefix the polished first message with “今日日报已生成，以下是完整日报正文：” and send the resulting plain-text messages in order through the current inbound QQ conversation. Do not send raw Markdown or the prefix as a separate message.
5. Do not derive a filename from the date, rerun generation, or treat file creation as delivery. If reading, polishing or sending fails, report the failed stage/part and keep the returned path for retry.

The local splitter preserves section boundaries, complete links, fenced code blocks and `partial` source states before polishing. The polishing step removes only presentation syntax and does not create a second delivery channel. Cron remains local report generation.
