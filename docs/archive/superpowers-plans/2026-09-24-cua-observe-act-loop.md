# CUA observe-act 标准回路接入 Agent — 实现计划

> **已归档（2026-10-03）**：该计划已全部落地（契约层 15 动作与元素寻址、提示层 observe-act 规则 15/16、截图按需回填存储 URL 均已实现）。当前能力说明见 [08-os-automation.md](../../prd/modules/08-os-automation.md) 与 `api/internal/core/tools/builtin_tools/providers/computer_control/computer_action.py`；本文档仅保留实施过程，**不代表当前实现**。

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 Agent 真正用上 cua 结构化能力——契约层声明 15 动作与元素寻址、提示层教 observe-act 循环、视觉层按需回填截图 URL。

**Architecture:** 只改 Agent 侧三处（工具契约描述、系统提示词、图片门禁常量）+ `computer_action` 结果后处理（base64→存储 URL）；worker/bridge/cua-driver 零改动（执行端能力已完备）。

**Tech Stack:** Python / pydantic / quart / pytest；YAML seed 提示词。

**规格:** `docs/archive/superpowers-specs/2026-09-24-cua-observe-act-loop-design.md`（已获批）

**执行约定（覆盖本计划的 Commit 步骤）:** 本仓库当前**未获提交授权**——所有标注 Commit 的步骤统一**跳过**（改动留在工作树），待用户明确指示后统一提交。

---

### Task 1: A1 契约层 — `computer_action` 描述声明 cua 能力

**Files:**
- Modify: `api/internal/core/tools/builtin_tools/providers/computer_control/computer_action.py`
- Test: `api/test/internal/core/tools/test_computer_action_tool.py`（追加）

- [ ] **Step 1: 写失败测试（追加到 test_computer_action_tool.py 末尾）**

```python
def test_computer_action_contract_exposes_cua_observability():
    """契约层：Agent 必须能从 schema 描述发现 cua 观察-行动能力。"""
    description = ComputerActionInput.model_fields["actions"].description or ""
    for token in (
        "capture",
        "include_accessibility_tree",
        "element_index",
        "element_token",
        "pid",
        "window_id",
        "list_apps",
        "list_windows",
        "launch_app",
        "double_click",
        "right_click",
        "drag",
        "set_value",
        "verified",
        "escalation",
        "return_base64",
    ):
        assert token in description, f"actions 描述缺少能力 token: {token}"


def test_computer_action_tool_description_teaches_observe_act():
    tool_desc = ComputerActionTool().description
    assert "capture" in tool_desc
    assert "元素树" in tool_desc
    assert "element_index" in tool_desc
```

（文件头部已有 `ComputerActionTool` 导入；`ComputerActionInput` 需补进第 5-7 行的 import：

```python
from internal.core.tools.builtin_tools.providers.computer_control.computer_action import (
    ComputerActionInput,
    ComputerActionTool,
)
```

）

- [ ] **Step 2: 运行确认失败**

Run（cwd=`api`）: `python -m pytest test/internal/core/tools/test_computer_action_tool.py::test_computer_action_contract_exposes_cua_observability -v --no-cov`
Expected: FAIL（`actions 描述缺少能力 token: capture`）

- [ ] **Step 3: 实现 — 替换 `ComputerActionInput.actions` 的 Field description**

```python
class ComputerActionInput(BaseModel):
    """计算机操作输入。"""

    actions: list[dict[str, Any]] = Field(
        ...,
        description=(
            "动作序列，每项为 {action, ...}。"
            "【前台坐标动作】move/click/scroll/type/press/hotkey/screenshot："
            "需 x/y 坐标（scroll 用 amount 正负控制方向）。"
            "【cua 观察】capture：返回目标窗口可访问性元素树"
            "（tree_markdown / elements，每项含 element_index 供后续寻址）；"
            "参数 include_accessibility_tree / include_screenshot（默认均 true），"
            "可附 pid 或 window_id 绑定窗口。"
            "【cua 元素寻址】click/double_click/right_click/set_value/type/press/scroll "
            "可带 element_index 或 element_token（来自 capture 结果）按元素定位，"
            "带元素参数时 click 类动作不需要 x/y；set_value 需 value。"
            "【cua 应用管理】list_apps / list_windows / launch_app"
            "（launch_app 需 name/path/aumid/bundle_id 之一）。"
            "【cua 拖拽】drag：需 from_x/from_y/to_x/to_y 坐标（可附 pid/window_id 定位窗口）。"
            "【行为语义】cua 动作由桌面端 cua-driver 后台执行，不抢焦点、不移动真实鼠标；"
            "回执含 verified/effect/escalation（delivery=background|foreground），"
            "据此判断执行效果，仅当动作被结构化拒绝（escalation）时才升级为前台坐标方式。"
            "【截图回传】screenshot/capture 仅当 return_base64=true 时回传存储 URL"
            "（默认不回传，节省流量与配额）。"
        ),
    )
```

同时替换工具 `description`（第 91-96 行）：

```python
    description: str = (
        "在用户授权的主机执行计算机控制，遵循「观察-行动」循环："
        "先用 capture 获取目标窗口可访问性元素树（tree_markdown，含 element_index），"
        "再按 element_index 元素寻址执行 click/set_value/type 等动作"
        "（cua 后台执行，不抢焦点、不移动真实鼠标）；"
        "回执 verified/effect/escalation 用于判断执行效果，"
        "仅当被结构化拒绝时才升级前台坐标方式。"
        "也支持前台坐标动作（move/click/scroll/type/press/hotkey/screenshot）"
        "与应用管理（list_apps/list_windows/launch_app）。"
        "⚠️ 仅当该账号有**在线桌面设备**时可用（执行端是桌面客户端）；"
        "Web 端无法操作用户本机，未安装桌面端时返回不可用。按高风险审批。"
    )
```

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest test/internal/core/tools/test_computer_action_tool.py -v --no-cov`
Expected: 全部 PASS（原 6 例 + 新 2 例 = 8）

- [ ] **Step 5: Commit（跳过，待用户授权）**

---

### Task 2: A3 视觉层 — 截图 base64 替换为存储 URL

**Files:**
- Modify: `api/internal/core/tools/builtin_tools/providers/computer_control/computer_action.py`
- Test: `api/test/internal/core/tools/test_computer_action_tool.py`（追加）

- [ ] **Step 1: 写失败测试（追加）**

```python
def test_computer_action_replaces_screenshot_base64_with_url(monkeypatch):
    """base64 绝不进工具结果：替换为存储 URL + markdown 内联。"""
    monkeypatch.setattr(
        module,
        "_call_worker",
        lambda payload: {"ok": True, "screenshot_base64": "aGVsbG8=", "results": []},
    )
    monkeypatch.setattr(
        module,
        "_persist_screenshot",
        lambda b64, requester: "https://cdn.example.com/computer_control_abc.png",
    )

    result = json.loads(
        ComputerActionTool(requester="acct-1")._run(
            actions=[{"action": "screenshot", "return_base64": True}]
        )
    )

    assert "screenshot_base64" not in result
    assert result["screenshot_url"] == "https://cdn.example.com/computer_control_abc.png"
    assert result["screenshot"] == "![screenshot](https://cdn.example.com/computer_control_abc.png)"
    assert result["screenshot_saved"] is True


def test_computer_action_screenshot_persist_failure_hides_base64(monkeypatch):
    """存储失败：标注 screenshot_saved=false，仍不回传 base64。"""
    monkeypatch.setattr(
        module,
        "_call_worker",
        lambda payload: {"ok": True, "screenshot_base64": "aGVsbG8="},
    )

    def boom(base64_str, requester):
        raise RuntimeError("storage down")

    monkeypatch.setattr(module, "_persist_screenshot", boom)

    result = json.loads(
        ComputerActionTool(requester="acct-1")._run(
            actions=[{"action": "screenshot", "return_base64": True}]
        )
    )

    assert "screenshot_base64" not in result
    assert result["screenshot_saved"] is False


def test_computer_action_result_without_screenshot_unchanged(monkeypatch):
    monkeypatch.setattr(
        module,
        "_call_worker",
        lambda payload: {"ok": True, "results": [{"action": "click", "ok": True}]},
    )

    result = json.loads(
        ComputerActionTool()._run(actions=[{"action": "click", "x": 1, "y": 1}])
    )

    assert "screenshot_url" not in result
    assert "screenshot_saved" not in result
    assert "screenshot_base64" not in result
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest test/internal/core/tools/test_computer_action_tool.py::test_computer_action_replaces_screenshot_base64_with_url -v --no-cov`
Expected: FAIL（`assert "screenshot_base64" not in result` 不成立——当前原样透传）

- [ ] **Step 3: 实现 — 在 `computer_action.py` 模块级（`_call_worker` 之后）加两个函数**

```python
def _persist_screenshot(base64_str: str, requester: str) -> str:
    """截图落存储并返回稳定 URL（FileCenterService 权威入口）。失败抛错交调用方兜底。"""
    import base64 as b64lib
    import uuid

    content = b64lib.b64decode(base64_str)
    filename = f"computer_control_{uuid.uuid4().hex}.png"
    if requester:
        from app.http.module import injector
        from internal.service.file_center_service import FileCenterService

        return injector.get(FileCenterService).save_generated_asset(
            requester,
            filename=filename,
            content=content,
            folder="generated-images",
        )["url"]
    from app.http.module import injector
    from internal.service.storage.runtime_storage_service import RuntimeStorageProxy

    return injector.get(RuntimeStorageProxy).upload_bytes_without_record(
        filename=filename,
        content=content,
        folder="generated-images",
    )


def _replace_screenshot(result: dict[str, Any], requester: str) -> dict[str, Any]:
    """把 worker 回传的 base64 截图替换为存储 URL。

    base64 绝不进工具结果（会撑爆 token）；存储失败时标注 screenshot_saved=false，
    元素树/动作回执等主干字段不受影响。
    """
    base64_str = str(result.pop("screenshot_base64", "") or "")
    if not base64_str:
        return result
    try:
        url = _persist_screenshot(base64_str, requester)
    except Exception:
        logger.warning("截图落存储失败", exc_info=True)
        result["screenshot_saved"] = False
        return result
    result["screenshot_saved"] = True
    result["screenshot_url"] = url
    result["screenshot"] = f"![screenshot]({url})"
    return result
```

并改 `ComputerActionTool._run`（第 100-106 行）：

```python
    def _run(self, **kwargs: Any) -> str:
        payload = {
            "actions": list(kwargs.get("actions") or []),
            "requester": _normalize_text(kwargs.get("requester") or self.requester),
        }
        result = _replace_screenshot(_call_worker(payload), str(payload["requester"]))
        return json.dumps(result, ensure_ascii=False, default=str)
```

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest test/internal/core/tools/test_computer_action_tool.py -v --no-cov`
Expected: 全部 PASS（11 例：原 6 + Task1 2 + 本任务 3）

- [ ] **Step 5: Commit（跳过，待用户授权）**

---

### Task 3: 图片 artifact 门禁 — `image_result_tool_names` 加 `computer_action`

**Files:**
- Modify: `api/internal/core/agent/entities/tool_policy_entity.py:18`
- Test: `api/test/internal/core/agent/test_tool_policy_entity.py`（追加）

- [ ] **Step 1: 写失败测试（追加）**

```python
def test_computer_action_is_image_result_tool_by_default():
    policy = ToolPolicy()

    assert policy.is_image_result_tool("computer_action")
    # 截图回填不改变审批语义：computer_action 仍只属高风险、不属 hard-fail
    assert not policy.is_hard_fail_tool("computer_action")
    assert policy.is_high_risk_tool("computer_action")
    # 原有默认成员不回归
    assert policy.is_image_result_tool("qwen_image_text_to_image")
    assert policy.is_hard_fail_tool("qwen_image_edit")
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest test/internal/core/agent/test_tool_policy_entity.py::test_computer_action_is_image_result_tool_by_default -v --no-cov`
Expected: FAIL（`is_image_result_tool("computer_action")` 为 False）

- [ ] **Step 3: 实现 — 替换 tool_policy_entity.py 第 18 行**

```python
_DEFAULT_IMAGE_RESULT_TOOL_NAMES = (*_DEFAULT_HARD_FAIL_TOOL_NAMES, "computer_action")
```

（注意：`hard_fail_tool_names` 字段仍引用 `_DEFAULT_HARD_FAIL_TOOL_NAMES`，不受影响。）

- [ ] **Step 4: 运行确认通过（含既有用例无回归）**

Run: `python -m pytest test/internal/core/agent/test_tool_policy_entity.py -v --no-cov`
Expected: 3 例全 PASS

- [ ] **Step 5: Commit（跳过，待用户授权）**

---

### Task 4: A2 提示层 — `assistant_agent_markdown_preset` 追加 observe-act 规则

**Files:**
- Modify: `api/internal/core/prompts/system_prompts.yaml`（`assistant_agent_markdown_preset` 的 content 末尾）
- Test: `api/test/internal/core/prompts/test_system_prompts_yaml.py`（新建）

- [ ] **Step 1: 写失败测试（新建文件）**

```python
"""system_prompts.yaml 内容契约：首页助手提示词必须含 observe-act 电脑控制协议。"""
from pathlib import Path

import internal.core
import yaml


def _preset_content() -> str:
    path = Path(internal.core.__file__).parent / "prompts" / "system_prompts.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    for item in data.get("prompts") or []:
        if item.get("key") == "assistant_agent_markdown_preset":
            return str(item.get("content") or "")
    raise AssertionError("assistant_agent_markdown_preset 未在 system_prompts.yaml 登记")


def test_assistant_preset_contains_observe_act_protocol():
    content = _preset_content()
    for token in (
        "capture",
        "element_index",
        "元素树",
        "escalation",
        "vision_analyze",
        "return_base64",
    ):
        assert token in content, f"observe-act 规则缺少 token: {token}"


def test_assistant_preset_keeps_existing_tool_rules():
    content = _preset_content()
    assert "os_file_task" in content
    assert "os_recycle_bin" in content
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest test/internal/core/prompts/test_system_prompts_yaml.py -v --no-cov`
Expected: FAIL（`observe-act 规则缺少 token: capture`），第 2 例 PASS

- [ ] **Step 3: 实现 — 在 `assistant_agent_markdown_preset` 的 content 中，规则 14 之后追加规则 15/16**

定位：`system_prompts.yaml` 中 `14. Agent 自建的测试脚本、调试文件、临时产物统一写入系统临时目录...` 这一行之后，追加两行（保持 6 空格缩进的块内列表格式）：

```yaml
      15. 操作电脑（computer_action）遵循「观察-行动」循环：先用 `capture` 动作获取目标窗口可访问性元素树（可附 pid/window_id 绑定窗口），按返回的 element_index 用元素寻址执行 click/set_value/type 等动作，不要盲点坐标；依据回执 verified/effect/escalation 判断执行效果，仅当动作被结构化拒绝（如后台不可用）时才升级为前台坐标方式。
      16. 需要理解屏幕画面（元素树覆盖不到的自绘界面）时：用 `screenshot`/`capture` 并显式传 return_base64=true 拿到截图存储 URL，再用 `vision_analyze` 分析该 URL（辅助手段，失败时以元素树为主继续任务，不要反复重试）。
```

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest test/internal/core/prompts/test_system_prompts_yaml.py -v --no-cov`
Expected: 2 例全 PASS

- [ ] **Step 5: 确认 YAML 同步不破坏（既有 prompt 同步测试）**

Run: `python -m pytest test/internal/service -k "prompt or system_prompt" -v --no-cov`
Expected: 全 PASS（content 变更不影响 key/结构同步；admin 编辑过的 custom 版本本就不被覆盖）

- [ ] **Step 6: Commit（跳过，待用户授权）**

---

### Task 5: 回归 + 架构文档同步 + 知识图谱

- [ ] **Step 1: 本计划全部测试 + 中间件回归**

Run（cwd=`api`）:

```
python -m pytest test/internal/core/tools/test_computer_action_tool.py test/internal/core/agent/test_tool_policy_entity.py test/internal/core/prompts/test_system_prompts_yaml.py test/internal/core/agent/test_deep_timeline_middleware.py test/internal/core/agent/test_function_call_and_react_agent.py --no-cov -q
```

Expected: 全 PASS（无新增失败；既有失败仅允许此前已知的 3 个库状态类失败，且不在此清单内）

- [ ] **Step 2: 挂载链回归（computer_action 挂载点不受描述变更影响）**

Run: `python -m pytest test/internal/service -k "assistant_agent" --no-cov -q`
Expected: 与改动前基线一致（不新增失败）

- [ ] **Step 3: 架构文档同步（AGENTS.md 强制规则）**

Modify: `docs/prd/modules/08-os-automation.md` §10.7，在该节末尾追加一条：

```markdown
- 2026-09-24 契约扩展（observe-act 回路）：`computer_action` 动作集声明扩至 15
  （前台 7 + cua 8：`capture/list_apps/list_windows/launch_app/double_click/right_click/drag/set_value`），
  支持 `pid/window_id/element_index/element_token` 元素寻址与 `capture` 元素树观察；
  `assistant_agent_markdown_preset` 新增规则 15/16（capture 先行 → 元素寻址 → 读
  `verified/effect/escalation` 回执 → 仅结构化拒绝才升级前台；视觉分析 `vision_analyze`
  仅作辅助）。截图仅 `return_base64=true` 时经 FileCenterService 落存储并以
  `![screenshot](url)` 内联（`image_result_tool_names` 已含 `computer_action`，
  base64 不进工具结果）。
```

- [ ] **Step 4: 知识图谱同步**

Run: `python -m graphify update .`
Expected: 更新成功

- [ ] **Step 5: 收尾接线自检（写进回复）**

用一行点明入口：`computer_action` 契约（15 动作 + 元素寻址）→ 挂载点 `assistant_agent_service` 既有注入 → observe 规则入口 `system_prompts.yaml/assistant_agent_markdown_preset`（DB custom 覆盖可改）→ 截图 URL 入口 `_replace_screenshot`（`return_base64=true` 触发）→ artifact 门禁 `ToolPolicy.image_result_tool_names`。
