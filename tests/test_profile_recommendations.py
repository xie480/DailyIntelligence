"""兴趣画像和推荐排序测试。"""

from __future__ import annotations

import unittest
from datetime import datetime
from pathlib import Path

from daily_intelligence.config import RuntimePaths
from daily_intelligence.database import Database
from daily_intelligence.models import Item
from daily_intelligence.profile import InterestProfileStore
from daily_intelligence.recommendations import RecommendationEngine
from tests.test_support import temporary_directory


class ProfileRecommendationTestCase(unittest.TestCase):
    """验证画像反馈、持久化和推荐历史边界。"""

    def setUp(self) -> None:
        """创建隔离运行目录和数据库。"""
        self.runtime_tempdir = temporary_directory(
            prefix="daily-intelligence-profile-",
        )
        self.addCleanup(
            self.runtime_tempdir.cleanup,
        )
        self.runtime_dir = Path(
            self.runtime_tempdir.name
        )
        self.paths = RuntimePaths.from_data_dir(self.runtime_dir)
        self.paths.ensure()
        self.database = Database(self.paths.database_path)
        self.database.initialize()
        self.profile = InterestProfileStore(
            self.paths,
            self.database,
        )

    def tearDown(self) -> None:
        """关闭数据库并删除隔离目录。"""
        self.database.close()

    def test_explicit_feedback_has_priority_and_persists(self) -> None:
        """明确反馈应调整权重并能被新实例读取。"""
        before = self.profile.load()["interests"]["MCP"]

        result = self.profile.apply_feedback("多关注 MCP")
        after = self.profile.load()["interests"]["MCP"]

        self.assertEqual(result.action, "increase_interest")
        self.assertGreater(after, before)
        reloaded = InterestProfileStore(
            self.paths,
            self.database,
        ).load()
        self.assertEqual(reloaded["interests"]["MCP"], after)

    def test_profile_supports_exclusion_disable_and_reset(self) -> None:
        """画像应支持排除项目、关闭和重置。"""
        self.profile.apply_feedback(
            "收藏这个项目",
            target="acme/favorite",
        )
        self.assertIn(
            "acme/favorite",
            self.profile.load()["favorite_projects"],
        )
        self.profile.apply_feedback(
            "不要再推荐这个项目",
            target="acme/demo",
        )
        self.assertIn(
            "acme/demo",
            self.profile.load()["excluded_projects"],
        )

        self.profile.apply_feedback("关闭兴趣画像")
        self.assertFalse(self.profile.load()["enabled"])

        self.profile.reset()
        restored = self.profile.load()
        self.assertTrue(restored["enabled"])
        self.assertNotIn(
            "acme/demo",
            restored["excluded_projects"],
        )
        self.assertNotIn(
            "acme/favorite",
            restored["favorite_projects"],
        )

    def test_implicit_signal_requires_repeated_evidence(self) -> None:
        """一次偶然信号不应改变长期权重，重复三次才轻量调整。"""
        before = self.profile.load()["interests"]["MCP"]

        self.profile.record_implicit_signal(
            "MCP",
            "连续研究部署",
        )
        self.profile.record_implicit_signal(
            "MCP",
            "连续研究部署",
        )
        self.assertEqual(
            self.profile.load()["interests"]["MCP"],
            before,
        )
        self.profile.record_implicit_signal(
            "MCP",
            "连续研究部署",
        )

        self.assertGreater(
            self.profile.load()["interests"]["MCP"],
            before,
        )

    def test_recommendation_matches_interest_and_skips_recent_history(self) -> None:
        """推荐应优先匹配兴趣，并跳过 30 天内已推荐项目。"""
        matching_id = self.database.upsert_item(
            Item(
                item_type="github",
                title="acme/agent-runtime",
                url="https://github.com/acme/agent-runtime",
                source="GitHub Search API",
                summary="MCP agent harness for local coding",
                category="AI Agent",
                repo_full_name="acme/agent-runtime",
                stars=500,
                metadata={"topics": ["agent", "mcp"]},
            )
        )
        excluded_id = self.database.upsert_item(
            Item(
                item_type="github",
                title="acme/noisy-wrapper",
                url="https://github.com/acme/noisy-wrapper",
                source="GitHub Search API",
                summary="Generic AI wrapper",
                category="AI Agent",
                repo_full_name="acme/noisy-wrapper",
                stars=5000,
            )
        )
        old_id = self.database.upsert_item(
            Item(
                item_type="news",
                title="Old model release",
                url="https://example.com/old",
                source="Example",
                summary="Model release details",
                category="ai",
            )
        )
        self.database.save_feedback(
            action="recommended",
            target="acme/agent-runtime",
            item_id=matching_id,
        )
        self.profile.apply_feedback(
            "不要再推荐这个项目",
            target="acme/noisy-wrapper",
        )

        engine = RecommendationEngine(
            self.database,
            self.profile,
        )
        results = engine.recommend(
            limit=10,
            record=False,
        )
        result_ids = {
            result["id"]
            for result in results
        }

        self.assertNotIn(matching_id, result_ids)
        self.assertNotIn(excluded_id, result_ids)
        self.assertIn(old_id, result_ids)

    def test_significant_star_growth_allows_recommendation_again(self) -> None:
        """七天内显著 Star 增长应允许项目突破推荐冷却。"""
        item_id = self.database.upsert_item(
            Item(
                item_type="github",
                title="acme/growing-agent",
                url="https://github.com/acme/growing-agent",
                source="GitHub Search API",
                summary="Agent harness",
                category="AI Agent",
                repo_full_name="acme/growing-agent",
                stars=250,
            )
        )
        self.database.save_repo_snapshot(
            "acme/growing-agent",
            "2026-11-14",
            100,
            10,
        )
        self.database.save_repo_snapshot(
            "acme/growing-agent",
            "2026-11-21",
            250,
            20,
        )
        self.database.save_feedback(
            action="recommended",
            target="acme/growing-agent",
            item_id=item_id,
        )

        results = RecommendationEngine(
            self.database,
            self.profile,
        ).recommend(
            limit=10,
            now=datetime.fromisoformat(
                "2026-11-21T12:00:00+00:00"
            ),
            record=False,
        )

        self.assertIn(
            item_id,
            {
                result["id"]
                for result in results
            },
        )


if __name__ == "__main__":
    unittest.main()

