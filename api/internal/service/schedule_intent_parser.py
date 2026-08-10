import json
import logging
import re
from datetime import UTC, datetime, timezone
from zoneinfo import ZoneInfo

from croniter import croniter

from internal.exception import FailException


logger = logging.getLogger(__name__)


class ScheduleIntentParser:
    """把用户的模糊需求解析为：6 段 cron + 精化 prompt + 缺失字段反问

    提示词统一从系统提示词库读取（system_prompts.yaml 默认值，管理员可编辑覆盖）；
    模型走公共 AI 功能配置（feature_key=schedule_intent_parser）。
    """

    PROMPT_KEY = "schedule_intent_parser_prompt"
    FEATURE_KEY = "schedule_intent_parser"

    def parse(self, user_input: str, history: list[dict] | None = None) -> dict:
        """解析用户需求（可携带多轮补全历史），返回结构化意图。"""
        from internal.service.language_model_service import LanguageModelService
        from internal.service.system_prompt_library_service import SystemPromptLibraryService

        # 公共 AI 功能配置：系统侧辅助调用，模型可在后台绑定/降级
        llm = LanguageModelService.get_feature_model(self.FEATURE_KEY)
        system_prompt = SystemPromptLibraryService().get_prompt_or_default(self.PROMPT_KEY)

        messages = self._build_messages(system_prompt, user_input, history)
        raw = llm.invoke(messages).content if hasattr(llm, "invoke") else str(llm(messages))
        return self._parse_json(raw)

    def _build_messages(self, system_prompt: str, user_input: str, history: list[dict] | None) -> list:
        try:
            from internal.core.entities.prompt import Prompt
        except ImportError:
            from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

            messages = [SystemMessage(system_prompt)]
            for turn in history or []:
                if turn.get("user"):
                    messages.append(HumanMessage(turn["user"]))
                if turn.get("assistant"):
                    messages.append(AIMessage(turn["assistant"]))
            messages.append(HumanMessage(user_input))
            return messages

        messages = [Prompt("system", system_prompt)]
        for turn in history or []:
            if turn.get("user"):
                messages.append(Prompt("user", turn["user"]))
            if turn.get("assistant"):
                messages.append(Prompt("assistant", turn["assistant"]))
        messages.append(Prompt("user", user_input))
        return messages

    def _parse_json(self, raw: str) -> dict:
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if not match:
            raise ValueError("解析失败：模型未返回 JSON")
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError:
            raise ValueError("解析失败：JSON 不合法")
        data.setdefault("missing_fields", [])
        data.setdefault("cron_expression", "0 0 0 * * *")
        data.setdefault("cron_humanized", "每天 00:00:00")
        data.setdefault("task_name", "定时任务")
        data.setdefault("prompt", "")
        return data

    def validate_cron(self, cron_expression: str) -> str:
        """校验并归一化 cron，非法时抛 FailException（由 handler 转 400）"""
        if not cron_expression:
            raise FailException("定时表达式不能为空")
        parts = cron_expression.strip().split()
        if len(parts) != 6:
            raise FailException("定时表达式需要 6 段：秒 分 时 日 月 周")
        try:
            croniter(cron_expression, datetime.now(UTC).replace(tzinfo=None), second_at_beginning=True)
        except Exception as exc:
            raise FailException(f"定时表达式不合法：{exc}")
        return cron_expression

    _WEEKDAY_NAMES = {0: "周日", 1: "周一", 2: "周二", 3: "周三", 4: "周四", 5: "周五", 6: "周六", 7: "周日"}

    def humanize(self, cron_expression: str) -> str:
        """把 6 段秒级 cron 转成中文时间描述。

        优先识别常见模式（每X秒/每分钟/每N分钟/每小时/每天/每周/每月）；
        无法识别时，用 croniter 取接下来 3 次执行时间（UTC 基准）兜底，
        并转为 Asia/Shanghai 本地时区展示。
        """
        cron_expression = cron_expression.strip()
        parts = cron_expression.split()
        if len(parts) == 6 and parts[5] != "*":
            # 周位 7 在标准 cron 中表示周日，但 croniter 6.x 不接受，统一归一化为 0（语义等价）
            dow = parts[5]
            if dow == "7":
                parts[5] = "0"
            elif "," in dow:
                parts[5] = ",".join("0" if part.strip() == "7" else part for part in dow.split(","))
            cron_expression = " ".join(parts)
        cron_expression = self.validate_cron(cron_expression)
        second, minute, hour, dom, month, dow = cron_expression.strip().split()

        is_num = lambda tok: tok.isdigit()
        is_step = lambda tok: tok.startswith("*/") and tok[2:].isdigit()
        all_star = lambda *toks: all(tok == "*" for tok in toks)

        # 每X秒：*/N * * * * *
        if is_step(second) and all_star(minute, hour, dom, month, dow):
            return f"每{int(second[2:])}秒"
        # 每分钟：秒位固定，其余全部通配
        if is_num(second) and all_star(minute, hour, dom, month, dow):
            if int(second) == 0:
                return "每分钟"
            return f"每分钟第{int(second)}秒"
        # 每N分钟：0 */N * * * *
        if second == "0" and is_step(minute) and all_star(hour, dom, month, dow):
            return f"每{int(minute[2:])}分钟"
        # 每小时：秒/分固定，时位通配
        if is_num(second) and is_num(minute) and hour == "*" and all_star(dom, month, dow):
            if int(minute) == 0:
                return "每小时"
            return f"每小时第{int(minute)}分"
        # 每天固定时刻：秒/分/时固定，日/月/周通配
        if all(is_num(tok) for tok in (second, minute, hour)) and all_star(dom, month, dow):
            return f"每天 {int(hour):02d}:{int(minute):02d}:{int(second):02d}"
        # 每周固定时刻：秒/分/时固定，日/月通配，周位指定
        if all(is_num(tok) for tok in (second, minute, hour)) and all_star(dom, month) and dow != "*":
            return f"每{self._weekday_desc(dow)} {int(hour):02d}:{int(minute):02d}:{int(second):02d}"
        # 每月固定时刻：秒/分/时固定，日位指定，月/周通配
        dom_fixed = dom.isdigit() or ("," in dom and all(tok.isdigit() for tok in dom.split(",")))
        if all(is_num(tok) for tok in (second, minute, hour)) and dom_fixed and all_star(month, dow):
            return f"每月{self._dom_desc(dom)} {int(hour):02d}:{int(minute):02d}:{int(second):02d}"
        # 兜底：接下来 3 次执行时间（UTC 转 Asia/Shanghai）
        base = datetime.now(UTC).replace(tzinfo=None)
        iterator = croniter(cron_expression, base, second_at_beginning=True)
        tz_shanghai = ZoneInfo("Asia/Shanghai")
        formatted = "、".join(
            item.replace(tzinfo=timezone.utc).astimezone(tz_shanghai).strftime("%Y-%m-%d %H:%M:%S")
            for item in (iterator.get_next(datetime) for _ in range(3))
        )
        return f"下次执行：{formatted}"

    def _weekday_desc(self, dow: str) -> str:
        """周位数值映射：1=周一..7=周日/0=周日，支持逗号列表与区间"""
        if dow.isdigit():
            return self._WEEKDAY_NAMES.get(int(dow), f"星期{int(dow)}")
        if "," in dow and all(part.isdigit() for part in dow.split(",")):
            return "、".join(self._WEEKDAY_NAMES.get(int(part), f"星期{int(part)}") for part in dow.split(","))
        if "-" in dow and dow.replace("-", "").isdigit():
            start, end = dow.split("-")
            return f"{self._WEEKDAY_NAMES.get(int(start), '星期' + start)}至{self._WEEKDAY_NAMES.get(int(end), '星期' + end)}"
        return dow

    def _dom_desc(self, dom: str) -> str:
        """日位描述：支持单值、逗号列表"""
        if dom.isdigit():
            return f"{int(dom)}号"
        if "," in dom and all(part.isdigit() for part in dom.split(",")):
            return "、".join(f"{int(part)}号" for part in dom.split(","))
        return dom
