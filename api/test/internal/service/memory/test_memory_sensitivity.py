"""记忆敏感度分级与读取确认（2026-10-05）。

不变量：
1. 只有明确识别为机密的记忆才需要确认（身份证/手机号/银行卡/邮箱/密码/验证码/密钥）；
   其余全部是普通记忆，**召回不需要任何确认**；
2. 机密记忆默认不注入，且给模型的提示要它先请用户确认（不得声称"没有任何记录"）；
3. 用户明确确认（短句确认语）后才放行机密记忆；
4. 占位摘要（全"暂无/无"）视为未命中——否则会把"用户画像：暂无"注入提示词；
5. 中文关系谓词归一化为合法边类型，不再丢边。
"""
from __future__ import annotations

from uuid import uuid4

import pytest

from internal.model.memory_models import RetrievalOptions, RetrievalResult
from internal.service.memory.ledger_writer import normalize_relation_type
from internal.service.memory.retriever import MemoryRetriever, digest_has_substance
from internal.service.memory.sensitivity import (
    SENSITIVITY_CONFIDENTIAL,
    SENSITIVITY_NORMAL,
    classify,
    is_read_confirmation,
    sensitivity_label,
)

OWNER = str(uuid4())

# 两个真实样本（取自实机 Digest 缓存）
_PLACEHOLDER_DIGEST = (
    "更新时间：2026-10-05 10:48\n\n"
    "用户画像：暂无  \n已习得技能：暂无  \n长期主题：无  \n近期事件：暂无  \n待办任务：暂无"
)
_RICH_DIGEST = (
    "更新时间: 2026-10-05 11:02\n\n== 用户画像 ==\n"
    "- 偏好：喜欢吃苹果；喜欢喝美式咖啡\n- 常驻地：杭州\n\n== 近期事件 ==\n"
    "- [2026-10-05T11:00] 用户表示：住在杭州，喜欢吃苹果"
)


class TestClassify:
    @pytest.mark.parametrize(
        "text,types",
        [
            ("我的身份证号是 110101199001011234", ["id_card"]),
            ("电话 13812345678 随时联系我", ["phone"]),
            ("卡号 6222021234567890123", ["bank_card"]),
            ("邮箱是 user@example.com", ["email"]),
            ("我的密码是 abc12345", ["password"]),
            ("验证码 889911", ["otp"]),
        ],
    )
    def test_confidential_types(self, text, types):
        level, hit = classify(text)
        assert level == SENSITIVITY_CONFIDENTIAL
        assert hit == types

    @pytest.mark.parametrize(
        "text",
        ["我喜欢吃苹果", "我住在杭州", "我养了一只猫叫小白", "昨天开会讨论了预算", ""],
    )
    def test_normal_memories_need_no_confirmation(self, text):
        level, hit = classify(text)
        assert level == SENSITIVITY_NORMAL and hit == []

    def test_label_renders_readable(self):
        assert sensitivity_label(["phone", "password"]) == "手机号、密码"
        assert sensitivity_label([]) == "敏感信息"


class TestReadConfirmation:
    @pytest.mark.parametrize("text", ["确认读取", "确认", "同意读取", "可以读", "读吧"])
    def test_short_affirmatives(self, text):
        assert is_read_confirmation(text) is True

    @pytest.mark.parametrize(
        "text",
        ["今天天气怎么样", "我想问问确认一下这个方案的细节，顺便聊聊其他事情好么", ""],
    )
    def test_long_or_unrelated_not_confirmation(self, text):
        assert is_read_confirmation(text) is False


class TestDigestSubstance:
    def test_placeholder_digest_is_not_substance(self):
        assert digest_has_substance(_PLACEHOLDER_DIGEST) is False
        assert digest_has_substance("") is False

    def test_rich_digest_has_substance(self):
        assert digest_has_substance(_RICH_DIGEST) is True

    def test_legacy_placeholder_digest_with_bullet_meta_is_not_substance(self):
        """旧模板把元数据渲染成 `- 更新时间：...`：不得被当成内容。

        真机缺陷（2026-10-05）：占位摘要被误判为命中 → 摘要优先的意图不再深检，
        记忆读回只拿到占位文本，机密确认卡片也拿不到。
        """
        legacy_placeholder = (
            "# 用户记忆摘要\n"
            "- 更新时间：2026-10-05 18:13\n"
            "- 用户画像：无\n"
            "- 已习得技能：无\n"
            "- 长期主题：无\n"
            "- 近期事件：无\n"
            "- 待办任务：无\n"
            "- 机密记忆规则：身份证/手机号/银行卡/密码/验证码/密钥等不进入摘要\n"
        )
        assert digest_has_substance(legacy_placeholder) is False

    def test_legacy_digest_with_real_bullets_has_substance(self):
        legacy_rich = (
            "# 用户记忆摘要\n"
            "- 更新时间：2026-10-05 18:13\n"
            "- 偏好：喜欢吃苹果；喜欢喝美式咖啡\n"
        )
        assert digest_has_substance(legacy_rich) is True

    def test_current_placeholder_digest_with_pii_rule_line_is_not_substance(self):
        """现网占位摘要（2026-10-05 真机样本）：说明行「机密记忆：身份证/手机号/…」不算内容。"""
        current_placeholder = (
            "更新时间：2026-10-05 18:55\n\n"
            "- 用户画像：暂无\n"
            "- 已习得技能：暂无\n"
            "- 长期主题：无\n"
            "- 近期事件：暂无\n"
            "- 待办任务：暂无\n"
            "- 机密记忆：身份证/手机号/银行卡/密码/验证码/密钥\n"
        )
        assert digest_has_substance(current_placeholder) is False

    def test_pii_rule_line_is_not_treated_as_content_but_user_memory_is(self):
        """判别性：同为 PII 词，模板说明行不算内容，用户自己的记忆算。"""
        assert digest_has_substance("- 机密信息：手机号/身份证号\n") is False
        assert digest_has_substance("- 联系方式：手机号 138xxxx，身份证号 110xxx\n") is True

    def test_system1_skips_placeholder_digest(self):
        class _Stub:
            def __init__(self, text):
                self.text = text

            def get_digest(self, owner_key):
                return self.text

        retriever = MemoryRetriever(neo4j_driver=None, db=None, digest_manager=_Stub(_PLACEHOLDER_DIGEST))
        assert retriever._system1_fast_path("q", OWNER) is None


class TestConfidentialRecallGate:
    @staticmethod
    def _patch_deep(monkeypatch, results):
        monkeypatch.setattr(
            MemoryRetriever,
            "_system2_deep_search",
            lambda self, query, owner_key, options: list(results),
        )

    def test_normal_memory_recalled_without_confirmation(self, monkeypatch):
        self._patch_deep(
            monkeypatch,
            [RetrievalResult(memory_id="m1", content="我喜欢吃苹果", score=1.0, source="bm25")],
        )
        retriever = MemoryRetriever(neo4j_driver=None, db=None)
        text = retriever.retrieve_for_chat("上周我说了什么", OWNER, max_chars=200)
        assert "苹果" in text and "系统提示" not in text

    def test_confidential_memory_withheld_and_hinted(self, monkeypatch):
        self._patch_deep(
            monkeypatch,
            [RetrievalResult(memory_id="m1", content="我的手机号是 13812345678", score=1.0, source="bm25")],
        )
        retriever = MemoryRetriever(neo4j_driver=None, db=None)
        text = retriever.retrieve_for_chat("我的手机号是多少", OWNER, max_chars=200)
        assert "13812345678" not in text
        assert "系统提示" in text and "确认" in text

    def test_confirmed_read_allows_confidential(self, monkeypatch):
        self._patch_deep(
            monkeypatch,
            [RetrievalResult(memory_id="m1", content="我的手机号是 13812345678", score=1.0, source="bm25")],
        )
        retriever = MemoryRetriever(neo4j_driver=None, db=None)
        from internal.entity.memory_recall_entity import ConfidentialAccess

        text = retriever.retrieve_for_chat(
            "确认读取", OWNER, max_chars=200, access=ConfidentialAccess.all()
        )
        assert "13812345678" in text and "系统提示" not in text

    def test_withheld_reports_structured_items(self, monkeypatch):
        """未放行的机密条目必须结构化回填 status["withheld"]（确认卡片的数据源）。"""
        self._patch_deep(
            monkeypatch,
            [RetrievalResult(memory_id="m1", content="我的手机号是 13812345678", score=1.0, source="bm25")],
        )
        retriever = MemoryRetriever(neo4j_driver=None, db=None)
        status: dict = {}
        retriever.retrieve_for_chat("我的手机号是多少", OWNER, max_chars=200, status=status)

        withheld = status["withheld"]
        assert len(withheld) == 1
        assert withheld[0]["memory_id"] == "m1"
        assert withheld[0]["label"] == "手机号"
        # 预览必须脱敏：不得出现原始号码
        assert "13812345678" not in withheld[0]["preview"]

    def test_id_whitelist_access_allows_only_authorized(self, monkeypatch):
        """白名单授权只放行被授权的 id，其余机密继续暂缓。"""
        from internal.entity.memory_recall_entity import ConfidentialAccess

        self._patch_deep(
            monkeypatch,
            [
                RetrievalResult(memory_id="m1", content="我的手机号是 13812345678", score=1.0, source="bm25"),
                RetrievalResult(memory_id="m2", content="我的身份证号是 110101199003071234", score=0.9, source="bm25"),
            ],
        )
        retriever = MemoryRetriever(neo4j_driver=None, db=None)
        status: dict = {}
        text = retriever.retrieve_for_chat(
            "我的证件信息",
            OWNER,
            max_chars=400,
            access=ConfidentialAccess.of_ids(["m1"]),
            status=status,
        )

        assert "13812345678" in text
        assert "110101199003071234" not in text
        assert [item["memory_id"] for item in status["withheld"]] == ["m2"]

    def test_status_sink_reports_route(self, monkeypatch):
        self._patch_deep(
            monkeypatch,
            [RetrievalResult(memory_id="m", content="片段", score=1.0, source="bm25")],
        )
        retriever = MemoryRetriever(neo4j_driver=None, db=None)
        status: dict = {}
        retriever.retrieve_for_chat("上周我做了什么", OWNER, max_chars=100, status=status)
        assert status["intent"] == "temporal"
        assert status["views"] == ["episodes"]
        assert status["prefer_deep"] is True


class TestRelationTypeNormalization:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("喜欢", "LIKES"),
            ("喜欢吃", "LIKES"),
            ("住在", "LIVES_IN"),
            ("认识", "KNOWS"),
            ("CONTAINS", "CONTAINS"),
            ("member_of", "MEMBER_OF"),
            ("某种无法识别的谓词", "RELATED_TO"),
            ("", "RELATED_TO"),
        ],
    )
    def test_normalization(self, raw, expected):
        assert normalize_relation_type(raw) == expected
