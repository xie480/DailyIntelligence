"""Bilibili 风控分类、冷却和客户端集成行为测试。"""

from __future__ import annotations

import json
import unittest
from urllib.error import HTTPError
from urllib.request import Request

from daily_intelligence.collectors.bilibili_risk import (
    BilibiliRiskControlError,
    BilibiliRiskController,
)
from daily_intelligence.collectors.creators import BilibiliClient


class FakeClock:
    """为风控冷却测试提供可控的单调时钟。"""

    def __init__(self) -> None:
        """初始化虚拟时间。"""
        self.value = 0.0

    def now(self) -> float:
        """返回当前虚拟时间。"""
        return self.value

    def sleep(self, seconds: float) -> None:
        """推进虚拟时间，避免测试真实等待。"""
        self.value += seconds


class FakeResponse:
    """提供 urllib 响应对象所需的最小接口。"""

    def __init__(
        self,
        payload: bytes,
    ) -> None:
        """保存响应体。"""
        self.payload = payload

    def read(self) -> bytes:
        """返回响应体。"""
        return self.payload

    def close(self) -> None:
        """兼容 urllib 的关闭调用。"""


class SequenceOpener:
    """按请求顺序返回响应或抛出异常。"""

    def __init__(
        self,
        outcomes: list[FakeResponse | BaseException],
    ) -> None:
        """保存离线响应序列。"""
        self.outcomes = outcomes
        self.requests: list[Request] = []

    def __call__(
        self,
        request: Request,
        timeout: float,
    ) -> FakeResponse:
        """记录请求并返回下一项结果。"""
        self.requests.append(request)
        if not self.outcomes:
            raise AssertionError("离线响应序列已耗尽")
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    def open(
        self,
        request: Request,
        timeout: float,
    ) -> FakeResponse:
        """兼容 urllib opener 的 open 方法。"""
        return self(
            request,
            timeout,
        )


def bilibili_nav_payload() -> bytes:
    """生成包含 WBI 图片地址的 nav 响应。"""
    return json.dumps(
        {
            "code": 0,
            "data": {
                "wbi_img": {
                    "img_url": "https://img.example/img-key.png",
                    "sub_url": "https://img.example/sub-key.png",
                },
            },
        }
    ).encode("utf-8")


def bilibili_video_payload(
    code: int = 0,
) -> bytes:
    """生成投稿接口响应。"""
    return json.dumps(
        {
            "code": code,
            "message": "risk control" if code else "0",
            "data": {
                "list": {
                    "vlist": [],
                },
                "page": {
                    "pages": 1,
                    "pn": 1,
                    "ps": 30,
                },
            },
        }
    ).encode("utf-8")


class BilibiliRiskControllerTestCase(unittest.TestCase):
    """验证风控状态机的阻断、退避和恢复。"""

    def test_http_412_enters_cooldown_and_blocks_follow_up_request(self) -> None:
        """HTTP 412 应记录风控并在冷却期内阻断后续请求。"""
        clock = FakeClock()
        controller = BilibiliRiskController(
            base_cooldown_seconds=60.0,
            max_cooldown_seconds=120.0,
            minimum_request_interval_seconds=0.0,
            clock=clock.now,
            sleep=clock.sleep,
        )

        failure = controller.record_failure(
            "dynamic",
            endpoint="/x/polymer/web-dynamic/v1/feed/space",
            http_status=412,
        )

        self.assertIsInstance(
            failure,
            BilibiliRiskControlError,
        )
        assert failure is not None
        self.assertEqual(
            failure.http_status,
            412,
        )
        with self.assertRaises(BilibiliRiskControlError) as context:
            controller.before_request("dynamic")
        self.assertEqual(
            context.exception.http_status,
            412,
        )
        self.assertEqual(
            context.exception.endpoint,
            "/x/polymer/web-dynamic/v1/feed/space",
        )
        self.assertEqual(
            context.exception.retry_after_seconds,
            60.0,
        )

    def test_success_clears_cooldown_and_second_failure_backoffs(self) -> None:
        """成功请求应清除状态，下一次风控从基础冷却重新计算。"""
        clock = FakeClock()
        controller = BilibiliRiskController(
            base_cooldown_seconds=60.0,
            max_cooldown_seconds=120.0,
            minimum_request_interval_seconds=0.0,
            clock=clock.now,
            sleep=clock.sleep,
        )

        controller.record_failure(
            "video",
            endpoint="/x/space/wbi/arc/search",
            code=-352,
        )
        clock.value = 60.0
        controller.before_request("video")
        controller.record_success("video")
        second_failure = controller.record_failure(
            "video",
            endpoint="/x/space/wbi/arc/search",
            code=-352,
        )

        assert second_failure is not None
        self.assertEqual(
            second_failure.retry_after_seconds,
            60.0,
        )

    def test_before_request_enforces_minimum_interval(self) -> None:
        """相邻接口请求之间应保持配置的最小间隔。"""
        clock = FakeClock()
        controller = BilibiliRiskController(
            minimum_request_interval_seconds=5.0,
            clock=clock.now,
            sleep=clock.sleep,
        )

        controller.before_request("nav")
        clock.value = 1.0
        controller.before_request("video")

        self.assertEqual(
            clock.value,
            5.0,
        )


class BilibiliClientRiskIntegrationTestCase(unittest.TestCase):
    """验证 Bilibili 客户端把接口风险响应交给风控层。"""

    def test_http_412_is_not_retried_and_is_classified(self) -> None:
        """HTTP 412 不应消耗通用重试次数，也不应重复打接口。"""
        clock = FakeClock()
        opener = SequenceOpener(
            [
                HTTPError(
                    "https://api.bilibili.com/x/polymer/web-dynamic/v1/feed/space",
                    412,
                    "precondition failed",
                    {},
                    None,
                ),
            ]
        )
        client = BilibiliClient(
            opener=opener,
            retries=2,
            risk_controller=BilibiliRiskController(
                base_cooldown_seconds=60.0,
                minimum_request_interval_seconds=0.0,
                clock=clock.now,
                sleep=clock.sleep,
            ),
            sleep=clock.sleep,
        )

        with self.assertRaises(BilibiliRiskControlError) as context:
            client.fetch_dynamic_page("123456")
        self.assertEqual(
            context.exception.http_status,
            412,
        )
        self.assertEqual(
            len(opener.requests),
            1,
        )
        with self.assertRaises(BilibiliRiskControlError):
            client.fetch_dynamic_page("123456")
        self.assertEqual(
            len(opener.requests),
            1,
        )

    def test_code_minus_352_refreshes_wbi_on_next_allowed_request(self) -> None:
        """-352 应清理旧 WBI，冷却后下一次请求重新获取 key。"""
        clock = FakeClock()
        opener = SequenceOpener(
            [
                FakeResponse(
                    bilibili_nav_payload(),
                ),
                FakeResponse(
                    bilibili_video_payload(
                        code=-352,
                    ),
                ),
                FakeResponse(
                    bilibili_nav_payload(),
                ),
                FakeResponse(
                    bilibili_video_payload(),
                ),
                FakeResponse(
                    bilibili_video_payload(),
                ),
            ]
        )
        client = BilibiliClient(
            opener=opener,
            cookie="SESSDATA=secret-value",
            risk_controller=BilibiliRiskController(
                base_cooldown_seconds=60.0,
                minimum_request_interval_seconds=0.0,
                clock=clock.now,
                sleep=clock.sleep,
            ),
            sleep=clock.sleep,
        )

        with self.assertRaises(BilibiliRiskControlError) as context:
            client.fetch_video_page(
                "123456",
                1,
            )
        self.assertEqual(
            context.exception.code,
            -352,
        )
        self.assertEqual(
            len(opener.requests),
            2,
        )
        self.assertEqual(
            opener.requests[1].get_header("Cookie"),
            "SESSDATA=secret-value",
        )

        clock.value = 60.0
        client.fetch_video_page(
            "123456",
            1,
        )
        self.assertEqual(
            len(opener.requests),
            4,
        )
        client.fetch_video_page(
            "123456",
            1,
        )
        self.assertEqual(
            len(opener.requests),
            5,
        )


if __name__ == "__main__":
    unittest.main()
