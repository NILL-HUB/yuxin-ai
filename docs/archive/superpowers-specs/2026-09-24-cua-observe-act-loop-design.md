# CUA observe-act 标准回路接入 Agent —— 设计规格

> **已归档（2026-10-03）**：该设计已全部落地。当前能力说明见 [08-os-automation.md](../../prd/modules/08-os-automation.md) 与 `api/internal/core/tools/builtin_tools/providers/computer_control/computer_action.py`；本文档仅保留设计过程与决策依据，**不代表当前实现**。

- 日期：2026-09-24
- 状态：已落地（设计期标注「未实现」为当时状态；2026-10-03 归档）
- 关联：[CLI 工具池设计规格](./2026-09-24-cli-tool-pool-design.md)（A3 视觉辅助与之互补）

## 1. 背景与现状核实（三层断链）

执行端（桌面 bridge → cua-driver）能力已完备，但 Agent 契约层停在 7 个前台动作，
导致 cua 的结构化/后台优势在运行时 **0% 被利用**，实际退化为 pyautogui 式盲点坐标。

| 层 | 状态 | 代码事实 |
| --- | --- | --- |
| worker 能力 | ✅ 齐全 | `api/scripts/computer_control_worker.py`：`_CUA_ONLY_ACTIONS = {capture, list_apps, list_windows, launch_app, double_click, right_click, drag, set_value}`；`capture` 回 UIA 元素树（`tree_markdown`/`elements`/`element_count`）+ 结构化回执（`effect`/`verified`/`escalation`/`delivery`） |
| 挂载点 | ✅ 已接线 | `assistant_agent_service.py` 注入 `computer_control/computer_action`（`requester=account_id`） |
| Agent 契约 | ❌ 断 | `computer_control/computer_action.py` 的 `ComputerActionInput.actions` 描述只列 `move/click/scroll/type/press/hotkey/screenshot`，无 `capture`、无 `pid/window_id/element_index/element_token`、无 cua 动作 |
| 提示层 | ❌ 断 | `internal/core/prompts/system_prompts.yaml` 的 `assistant_agent_markdown_preset` 对 observe-act 零引导 |
| 视觉层 | ❌ 断 | worker 的 `screenshot_base64` 只塞 JSON；`ToolPolicy.image_result_tool_names` 仅含 3 个文生图工具，`computer_action` 不在其中 → 图片 artifact 链路不可达 |

**关键事实（概念澄清，避免混淆）**：
- `image-vision` 是 **Trae 宿主技能**（调免费视觉端点、不稳定）——本设计**不依赖它**。
- 仓库内工具是 **`vision_analyze`**：链路 `vision_analyze → invoke_vision_model → LanguageModelService.get_feature_model("vision_analyze") → public_ai_feature_config 表 admin 绑定的模型`（未绑定时诚实报「未配置视觉分析模型」），与免费端点无关。
- 即便如此，按产品决策 **vision 仍只作辅助**：主干是元素树（本地 cua-driver、纯文本、确定性），`vision_analyze` 仅在元素树不足（自绘界面）时补充。

## 2. 目标与非目标

**目标**：让 Agent 真正用上 cua 结构化能力——「先观察（capture 元素树）→ 元素寻址动作 → 读结构化回执」，截图作为辅助视觉通道按需可用。

**非目标**：
- 不改 worker、不改 bridge、不改 cua-driver（执行端已完备）；
- 不改高风险审批门（`computer_action` 仍默认不自动放行）；
- 不引入模型多模态依赖（看图走 `vision_analyze` 工具闭环，产出文本）。

## 3. 设计

### A1 契约层（`computer_control/computer_action.py`，只改描述不动转发）

`_run` 已把 `actions` 原样透传给 worker，worker 已支持全部 15 动作——本层**只补声明**：

1. **动作全集（15）**：`move/click/scroll/type/press/hotkey/screenshot` +
   `capture/list_apps/list_windows/launch_app/double_click/right_click/drag/set_value`。
2. **cua 目标参数**：`pid / window_id / element_index / element_token`——
   **元素寻址优先于 x/y 坐标**（带元素参数时不需要坐标）。
3. **capture 参数**：`include_screenshot`（默认 true）、`include_accessibility_tree`（默认 true）；
   返回 `tree_markdown` + `elements`（含 `element_index` 供后续寻址）。
4. **语义提示**：cua 后端为后台定向控制（不抢焦点、不移动真实光标）；
   回执含 `verified/effect/escalation`，按回执判断成败。
5. 工具 `description` 同步：从「移动/点击/输入/截屏」扩为「观察-行动循环」表述。

### A2 提示层（`system_prompts.yaml` 的 `assistant_agent_markdown_preset` 追加规则）

该 key 是首页助手的行为/工具裁决提示词，既有规则 10/13/14 已承载
`os_file_task`/`os_recycle_bin` 同类工具协议，位置与此一致。追加一条规则：

- 操作电脑前先用 `capture` 获取目标窗口元素树（可附 `pid`/`window_id` 绑定窗口），
  按 `element_index` 寻址执行动作，**不要盲点坐标**；
- 依据回执 `verified/effect/escalation` 判断是否成功；仅当动作被结构化拒绝
  （如后台不可用）时才升级前台坐标方式；
- 元素树无法覆盖（自绘界面/游戏）时，可用 `vision_analyze` 分析截图（辅助手段），
  截图 URL 由 `computer_action` 在显式要求（`return_base64=true`）时返回。

YAML 属 seed 数据（非代码硬编码），key 已在 `system_prompts.yaml` 清单内，
**无需新增 `index.yaml` 条目**；管理员可在系统提示词库编辑覆盖（source=custom 双源保护）。

### A3 视觉层（截图 → 存储 URL → artifact → vision_analyze 闭环）

1. **`computer_action.py`**：worker 返回 `screenshot_base64` 非空时（仅当
   `return_base64=true` 才会回传，**默认关闭**——避免每次 capture 计入文件配额）：
   - 经 `FileCenterService.save_generated_asset(account_id, filename, content, folder="generated-images")` 落存储，取回稳定 URL；
   - 结果 JSON 中**删除 base64、替换为 URL**（防 base64 灌入工具结果导致 token 爆炸）；
   - URL 以 markdown 图片语法内联：`![screenshot](url)` —— 已核实可被
     `DeepTimelineMiddleware._extract_inline_image_urls` 的 pattern 1
     （`!\[[^\]]*]\((https?://[^\s)]+)\)`）识别为 artifact（注意 URL 落存储时
     保留图片扩展名，供 `_build_image_artifact` 推断 mime）；
   - 存储失败时**不回传 base64**，返回 `screenshot_saved: false` 说明——
     元素树主干不受影响，Agent 仍可继续工作。
2. **`core/entities/tool_policy_entity.py`**：`image_result_tool_names` 增加
   `"computer_action"`（否则中间件不提取图片 artifact）。该常量随全局策略走，
   截图提取发生在 `status == "success"` 时，不改变审批语义。
3. **辅助定位**：`vision_analyze(image_url, prompt)` 消费 URL 产出文本描述，
   由 Agent 按需调用；失败（免费端点不稳的是宿主技能，此处是 admin 绑定模型）
   不影响主干——主干始终是元素树文本回路。

## 4. 数据流

```
Agent 调用 computer_action
  ├─ 观察: {action: "capture", pid|window_id?}
  │    → worker(cua) → get_window_state → {tree_markdown, elements[], effect/verified}
  │    → Agent 读元素树，获得 element_index
  ├─ 行动: {action: "click", element_index: N}（或 set_value/drag/...）
  │    → worker(cua 后台执行) → {verified, effect, escalation, delivery}
  │    → 结构化拒绝(escalation)时才升级前台坐标
  └─ 视觉(辅助, opt-in): {action: "screenshot", return_base64: true}
       → worker → base64 → 存储 URL(失败则标注未保存)
       → Agent 需要时调 vision_analyze(url) 得文本描述
```

## 5. 错误处理

| 场景 | 行为 |
| --- | --- |
| 无在线桌面设备 | 现状不变：诚实返回「不可用」并引导安装桌面端（`_call_worker` 分支） |
| cua 动作结构化拒绝 | worker 原样上报 `escalation/delivery`，提示词引导 Agent 判断是否升级，不静默降级 |
| 截图存储失败 | 返回 `screenshot_saved: false`，不回传 base64，元素树回路不受影响 |
| `vision_analyze` 未绑定模型 | 现状不变：返回 `{"ok": false, "error": "未配置视觉分析模型"}`（辅助通道，不影响主干） |

## 6. 测试策略

- **契约测试**：`ComputerActionInput` 描述含 `capture`、`element_index`、
  `include_accessibility_tree` 等关键 token；工具 description 含 observe 表述。
- **视觉回填测试**：mock `_call_worker` 返回 `screenshot_base64` → 断言结果含 URL、
  **不含 base64**；存储抛错 → 断言 `screenshot_saved: false` 且无 base64。
- **门禁测试**：`ToolPolicy.is_image_result_tool("computer_action") is True`。
- **提示词测试**：加载 `system_prompts.yaml` 断言 `assistant_agent_markdown_preset`
  含 observe-act 关键规则（防回退的文本契约守卫）。
- **回归**：既有 `computer_control` 相关测试（worker/挂载）保持通过。

## 7. 接线自检

- 能力入口：Agent 调 `computer_action`（已挂载，本次只扩契约）；
- observe 引导入口：`assistant_agent_markdown_preset` 新增规则（运行时经
  `SystemPromptLibraryService` 注入，YAML seed > admin 编辑覆盖）；
- 图片 artifact 入口：`ToolPolicy.image_result_tool_names` + 中间件提取（既有链路，
  本次只加成员）；
- 看图入口：`vision_analyze`（已挂载于 `assistant_agent_service`，本次不改）。
