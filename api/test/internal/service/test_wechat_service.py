"""WechatService 回归测试：Quart 单栈下 wechat() 不再依赖 Flask request 上下文。

背景：迁移 Quart 后，_to_thread 线程内只有 Flask app context（无 request context）。
原实现直接访问 Flask request（request.data/method/args）必然抛 RuntimeError。
修复后改为路由层显式传入 method/body/query，本文件验证该链路。
"""
import uuid
from types import SimpleNamespace

import pytest

from internal.entity.app_entity import AppStatus
from internal.entity.platform_entity import WechatConfigStatus
from internal.exception import FailException
from internal.service.wechat_service import WechatService


class TestWechatServiceNoRequestContext:
    """回归：wechat() 在无 Flask request context 环境下可正常执行业务链路。"""

    def _make_service(self, app):
        service = WechatService(
            db=SimpleNamespace(),
            retrieval_service=SimpleNamespace(),
            app_config_service=SimpleNamespace(),
            conversation_service=SimpleNamespace(),
            language_model_service=SimpleNamespace(),
        )
        service.get = lambda model, app_id: app
        return service

    def test_wechat_get_app_not_published(self):
        """应用不存在/未发布：GET 抛 FailException（而非 request context RuntimeError）。"""
        service = self._make_service(None)
        with pytest.raises(FailException, match="未发布"):
            service.wechat(uuid.uuid4(), method="GET", body=b"", query={})

    def test_wechat_get_signature_verification_flow(self):
        """已发布+已配置：签名校验链路可执行，证明未卡在 Flask request 访问。"""
        service = self._make_service(
            SimpleNamespace(
                id=uuid.uuid4(),
                status=AppStatus.PUBLISHED,
                wechat_config=SimpleNamespace(
                    status=WechatConfigStatus.CONFIGURED, wechat_token="test-token"
                ),
            )
        )
        with pytest.raises(FailException):
            # 无效签名 → check_signature 抛 InvalidSignatureException → FailException
            service.wechat(
                uuid.uuid4(),
                method="GET",
                body=b"",
                query={"signature": "bad", "timestamp": "1", "nonce": "2", "echostr": "x"},
            )
