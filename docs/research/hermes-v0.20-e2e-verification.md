# Hermes v0.20 对齐：端到端验证报告

> 验证日期：2026-08-13
> 范围：本目标内新增/改造能力的可执行验证与需要真实环境的 E2E 场景清单。

## 一、已验证项（自动化测试）

本轮全量回归：**295 个后端测试通过**，前端 `vue-tsc` 通过。

| 能力 | 验证方式 | 结果 |
| --- | --- | --- |
| V4A 补丁解析/应用 | `test_v4a_patch.py`（10 个） | ✅ |
| 敏感信息脱敏 | `test_redact.py`（9 个） | ✅ |
| 审批历史挖掘/熔断 | `test_approval_mining.py` + `test_approval_insights_service.py` | ✅ |
| 宿主机文件操作 worker | `test_os_automation_worker.py`（10 个） | ✅ |
| `os_file_task` Agent 工具 | `test_os_file_task_tool.py` | ✅ |
| 确认集成与 redirect | `test_tool_confirmation_integration.py`（17 个） | ✅ |
| 工具确认服务（含 webhook 分发） | `test_tool_confirmation_service.py`（9 个） | ✅ |
| HMAC webhook | `test_outbound_webhook.py`（4 个） | ✅ |
| A2A 协议/客户端/网关/HTTP | `test_a2a_*` + asgi A2A 用例（含 message/stream） | ✅ |
| 语音（STT/TTS 工具、分句 TTS） | `test_audio_tools.py` + `test_audio_service.py`（45 个） | ✅ |
| 网页搜索/提取 | `test_web_search_tool.py` + `test_web_extract_tool.py`（9 个） | ✅ |
| 视觉分析 | `test_vision_analyze_tool.py`（4 个） | ✅ |
| 沙箱代码执行 | `test_execute_code_tool.py`（5 个） | ✅ |
| 任务清单 | `test_todo_tool.py`（4 个） | ✅ |
| 前端确认/服务/页面 | `vue-tsc` + vitest | ✅ |

## 二、需要真实环境才能完成的 E2E

| 场景 | 依赖 | 建议执行方式 |
| --- | --- | --- |
| 宿主机“清理 C 盘”全链路（preview → 授权 → apply） | 本机 Codex CLI + OS automation worker | `python api/scripts/test_os_automation_e2e.py`（已有脚本） |
| 沙箱代码执行真实调用 | `E2B_API_KEY` / `E2B_DOMAIN` / `SANDBOX_TEMPLATE_ALIAS` | 配置后对 `execute_code` 发起真实命令 |
| 视觉分析真实调用 | 平台公共 AI `vision_analyze` 功能模型 | 配置模型后对真实图片调用 |
| 语音合成/识别真实调用 | SiliconFlow ASR/TTS 凭证 | Web 端录音与逐句播放 |
| A2A 跨系统互操作 | 外部 A2A 端点 | 用 Agent Card + `message/send` / `message/stream` 对连 |
| 多轮任务 + todo + 工具链组合 | 完整模型/工具配置 | 首页助手端到端对话 |

## 三、当前交付清单

首页助手已挂载工具：`run_os_task`、`os_file_task`、`web_search`、`web_extract`、`tts_speak`、`audio_transcribe`、`execute_code`（受开关保护）、`vision_analyze`、`todo`、`a2a_send_message`。

平台能力：A2A v1.0（Agent Card / message/send / tasks/get / message/stream / 出站）、HMAC 出站 webhook、确认续跑、确认期 mid-turn redirect、流式分句 TTS + barge-in、审批洞察。

## 四、剩余与建议

- 唤醒词、IM 多平台接入：独立阶段评估（涉及客户端/回调/合规）。
- 完整图级 mid-turn redirect：需 LangGraph 执行中断机制，另行立项。
- 上表真实环境 E2E 完成后，可把结果回填到本报告。

## 来源

- 对齐状态：`docs/research/hermes-v0.20-alignment-report.md`
- 功能对比：`docs/research/hermes-agent-v0-20-comparison.md`
