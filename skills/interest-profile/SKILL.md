---
name: interest-profile
description: 管理 Daily Intelligence 用户兴趣画像、显式反馈、隐式信号、收藏和排除列表。
version: 1.0.0
author: Daily Intelligence
license: MIT
platforms: [windows, linux, macos]
metadata:
  hermes:
    tags: [profile, feedback, preferences, recommendations]
    category: productivity
    related_skills: [daily-intelligence-local, github-radar, tech-news-radar]
---

# Interest Profile

## 适用场景

- 用户说“多推荐 Agent 项目”“多关注 MCP”“最近少看模型发布新闻”。
- 用户喜欢、收藏或排除某个项目。
- 用户要求查看、关闭、开启或重置画像。
- Hermes 需要记录重复关注某类技术的隐式信号。

## 执行流程

1. 从 config/user_profile.json 读取当前画像；不存在时创建默认兴趣方向。
2. 明确反馈直接调权或更新排除列表，优先级高于隐式信号。
3. 隐式信号只保存主题、次数和简短依据；累计三次才增加 2 分，单次提问不改变长期画像。
4. 收藏和喜欢记录到 favorite_projects，排除记录到 excluded_projects。
5. 使用原子文件替换保存 JSON，权重始终限制在 0～100。
6. 将 like、favorite、exclude_project、implicit_signal、reset、profile_enabled 等事件写入 SQLite feedback。
7. 推荐时读取 enabled、interests、favorite_projects、excluded_projects 和 excluded_topics。

## 输入与输出

~~~~powershell
python -m daily_intelligence --data-dir "E:\HermesData\daily-intelligence" feedback "多关注 MCP"
python -m daily_intelligence --data-dir "E:\HermesData\daily-intelligence" feedback "不要再推荐这个项目" --target "owner/repo"
python -m daily_intelligence --data-dir "E:\HermesData\daily-intelligence" profile show --json
python -m daily_intelligence --data-dir "E:\HermesData\daily-intelligence" profile disable
~~~~

输出是画像状态、反馈解析结果和推荐排序使用的结构化权重，不输出或保存完整聊天记录。

## 与其他 Skills 的关系

- daily-intelligence-local 把 Hermes 的自然语言反馈路由到本 Skill。
- github-radar 提供仓库标识，便于排除和收藏。
- tech-news-radar 提供新闻分类，便于调整 AI、Agent、软件开发主题权重。

## 错误处理

- 空反馈、损坏 JSON 和非法权重使用安全默认画像并保留错误边界。
- 重置后清空排除、证据和隐式计数，但保留默认兴趣方向。
- 画像关闭时推荐模块返回空结果，采集和历史数据不删除。

## 安全限制

- 只处理当前用户主动提供的上下文，不扫描其他用户会话。
- evidence 只保存不超过 160 字的简短依据和结构化变更。
- 不保存 Token、密码、完整聊天内容或与推荐无关的个人信息。

