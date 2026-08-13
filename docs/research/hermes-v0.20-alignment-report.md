# Hermes v0.20 能力对齐报告

> 目标：从 Hermes Agent v0.20（NousResearch/hermes-agent，MIT）选择性移植能力，
> 适配钰心AI 多租户 Web 平台形态。本报告逐项记录状态、落地文件、验证结果与剩余差距。

## 状态图例

- ✅ 已完成：实现 + 测试通过，运行时已挂载
- ◑ 部分完成：核心链路已通，剩余增强项
- ✗ 未完成/不适配：明确记录原因

## 一、语音与免手操作

| 能力 | 状态 | 落地 | 说明 |
| --- | --- | --- | --- |
| STT/TTS 独立工具分类 | ✅ | `api/internal/core/tools/builtin_tools/providers/audio_tools/` | `tts_speak` / `audio_transcribe`，复用 SiliconFlow 底座，已挂载首页助手；工具与 `/audio/audio-to-text` 支持 `language` / `provider` / `model` 透传 |
| 统一语言解析 | ✅ | `audio_service.py` | ASR/TTS 请求支持显式语言参数；ASR 提供 `gpt_transcribe`/`gpt-transcribe` provider 路由，或 `GPT_TRANSCRIBE_ENABLED=1` 开启，模型默认 `OpenAI/whisper-large-v3`，可用 `GPT_TRANSCRIBE_MODEL` 覆盖 |
| 流式分句 TTS（边说边生成） | ✅ | `audio_service.text_to_audio_sentences` + `/audio/text-to-audio?sentence_stream` + `use-audio.ts` MediaSource 渐进播放 | 后端按句合成逐句推送 `tts_sentence`，前端 MediaSource 边收边播 |
| barge-in（说话打断） | ✅ | `HomeView` / `PreviewDebugChat` / `IndexView` / `PublicPreviewDebugChat` | 录音开始即停止 TTS 并停止正在运行的 Agent（Assistant/WebApp/Debug stop + A2A tasks/cancel），服务端给空答案写入打断标记，下一轮模型可感知；四个 Web 表面均已覆盖，首页助手新增连续语音模式 |
| 设备端唤醒词 | ◑ | `scripts/wake_word_worker.py`（openWakeWord/sounddevice，可选） | 桌面端可用；Web 端以连续语音模式替代；桌面集成待发布验证 |
| 多 profile 语音路由 | ✅ | `audio_service._resolve_voice` + `AppConfig.text_to_speech` | 已按账号/应用级音色实现；profile 概念不适配 Web 多租户形态 |
| WhatsApp/Feishu/DingTalk/Line/QQ/Photon/Weixin 语音笔记 | ◑ | `im_voice_service.py` + `im_voice_routes.py` + `wechat_service.py` | 5 个平台已具备落地形态（微信闭环；LINE/WhatsApp/飞书/钉钉 webhook）；QQ 语音转写适配器保留、Bot 网关已移除；Photon 是 Hermes 私有协议，无对应平台映射；剩余为真实凭证部署验证 |

## 二、Agent 架构与执行

| 能力 | 状态 | 落地 | 说明 |
| --- | --- | --- | --- |
| A2A v1.0 插件（发现/对话/被驱动） | ✅ | `a2a_protocol.py` + `a2a_gateway_service.py` + `a2a_routes.py` | Agent Card + JSON-RPC（message/send、tasks/get、tasks/cancel、message/stream），已注册路由与 DI |
| A2A 出站（主动调用对端） | ✅ | `a2a_client.py` + `a2a_send_message` 工具 | 双向互操作闭环 |
| A2A message/stream（流式） | ✅ | `a2a_routes.py` | SSE `statusUpdate` + 最终 `message`，协议合规 |
| Mid-turn redirects | ✅ | `midturn_redirect.py`（request 级） + `function_call_agent._llm_node` + `/tool-confirmations/{id}/redirect` + `/subtasks/<request_id>/redirect` | 确认等待期与任意执行阶段均可注入纠正；`_llm_node` 每轮前消费并追加 HumanMessage 重新规划 |
| 智能审批：历史挖掘 allowlist | ✅ | `approval_mining.py` + `approval_insights_service.py` + `/admin/approval-insights` | dry-run 建议，破坏性工具永不建议 |
| 智能审批：策略自定义/熔断 | ✅ | `approval_mining.py` + `smart_approval_policy_service.py` | 熔断信号已产出；`tool_governance_policy.require_confirmation=false` 可运行时自动放行，危险工具永不自动放行 |
| Docker/podman daemon 危险命令审批门 | ✅ | `smart_approval_policy_service.contains_dangerous_container_command` + `FunctionCallAgent._smart_approval_allows(tool_input=...)` | `docker/podman run/exec/create` 含特权/宿主网络/进程/IPC/全 capability/设备直通/根目录挂载时，即使免确认策略开启也强制确认 |
| 工具自恢复：patch 已应用检测 | ✅ | `v4a_patch.py` | no-op 返回 + 空白差异诊断 |
| 工具自恢复：write_file 落盘校验 | ✅ | OS worker `/file` + `/output/<run_id>` | patch 应用后落盘校验；`web_search` 零结果结构化探测已接；Codex run 完整输出落盘并可回读 |
| 上下文压缩：尾巴保护/逐轮微压缩 | ✅ | `TokenBufferMemory` + `ContextCompressor` + `FunctionCallAgent` | RECENT_KEEP_MESSAGES、LLM 压缩、12k 字符工具结果兜底截断、最近 3 条用户消息硬保护、逐轮摊销压缩、已加载技能防幽灵重复注入 |
| 子代理委派/生命周期 API | ✅ | `MultiAgentExecutor` + `ExecutionCoordinatorService` + Redis 化 `subtask_registry_service.py` + `GET/POST /subtasks/<request_id>[/cancel]` + `SubtaskProgressPanel` + `execute_code` tool_calls RPC 桥 | 多子任务计划执行、registry 状态、SSE 实时事件、查询/取消接口、首页展示与脚本预取工具均已闭环 |

## 三、工具拆装（“干活能力”）

| 工具 | 状态 | 落地 | 说明 |
| --- | --- | --- | --- |
| 宿主机系统自动化 | ✅ | `run_os_task` + `os_automation_worker.py` | preview → approval_token → apply |
| 宿主文件读/补丁 | ✅ | `os_file_task` + worker `/file` | 安全根目录、V4A 补丁、一次性 token |
| 网页提取 | ✅ | `web_tools/web_extract` | SSRF 防护 + 大小限制 |
| 文本转语音/语音转文本 | ✅ | `audio_tools` | data URI 返回、URL 转写 |
| 网页搜索 | ✅ | `web_tools/web_search` | 统一入口：Tavily → SerpAPI → DuckDuckGo 自动降级，已挂载首页助手 |
| 视觉分析 | ✅ | `vision_tools/vision_analyze` | 复用平台视觉模型，支持 URL/data URI，带 SSRF 防护，已挂载首页助手 |
| 代码执行 | ✅ | `code_execution_tool/execute_code` | 复用 Baidu CFC/E2B 沙箱；支持 tool_calls 预取已挂载平台工具并以 `TOOL_RESULTS_JSON` 注入沙箱；默认关闭且按高风险工具确认 |
| 任务清单 | ✅ | `todo_tool/todo` | create/list/update/complete/delete，Redis 优先、内存兜底，已挂载首页助手 |

## 四、平台能力

| 能力 | 状态 | 落地 | 说明 |
| --- | --- | --- | --- |
| 确认后续跑/断点续传 | ✅ | `web_app_service.py` 生命周期解耦 + visitor_id + 轮询 | 前端断线不丢任务结果 |
| HMAC 签名出站 webhook | ✅ | `outbound_webhook.py` + 确认/取消事件 | 事件信封、重试、幂等 ID |
| 管理端审批洞察 | ✅ | `/admin/approval-insights` | dry-run |

## 五、验证汇总

- 后端相关测试：语音链路 123 个、内置工具装配 11 个、Assistant Agent 58 个、IM 语音多平台 22 个、IM webhook 路由 7 个、审批门 41 个、Agent 执行关键回归 173 个、A2A/公共预览 95 个、asgi 路由 188 个全部通过。
- 前端：`vue-tsc` 通过；确认/服务测试通过。
- 每次改动均运行目标测试集，未运行完整全仓 suite（工作区有大量用户未提交改动）。

## 六、建议的下一步

已完成项已闭环：请求级 redirect + A2A tasks/cancel、`web_search` 统一降级、`execute_code` 高风险确认挂载、四表面 stop、barge-in 模型感知、IM 多平台语音接入。

剩余建议：
1. 用真实平台凭证部署验证 LINE/WhatsApp/飞书/钉钉 语音链路。
2. webhook 随 API 服务启动；本地 Worker 由 docker-compose（`local-workers` profile）托管。
3. 浏览器自动化/计算机控制按多租户高风险评估后决定是否开放。

部署步骤与环境变量见 `docs/research/hermes-v0.20-deployment-guide.md`。

## 七、深度盘点后的新增差距（2026-08-13）

完整逐项盘点见 `docs/research/hermes-v0.20-capability-deep-dive.md`。本次新增确认的差距：

| 能力 | 状态 | 说明 |
| --- | --- | --- |
| 子任务实时状态查询 | ✅ | `MultiAgentExecutor` + Redis 化 registry + `GET /subtasks/<request_id>` + SSE `subtask_started/running/completed` + 首页 `SubtaskProgressPanel` |
| A2A tasks/cancel 与公共预览 stop | ✅ | `a2a_gateway_service.handle_tasks_cancel` + `public_agent_a2a_service.cancel_task` + `POST /public/apps/<id>/a2a/tasks/<task_id>/cancel` | 运行中的公共 Agent 可被取消，取消后写入 STOP 状态与“响应已停止”标记 |
| 技能 Curator 生命周期 | ✗ | Hermes 有使用统计、自动归档、恢复、备份；钰心AI 只有技能商店与 SkillEmergence |
| 学习图可视化 | ✗ | Hermes 有 learning graph；钰心AI 记忆图只展示记忆节点，无技能关联 |
| 会话导出/checkpoint 恢复 | ✗ | Hermes 支持 html/md 导出与 checkpoint；钰心AI 无 |
| 入站 webhook 事件触发 | ◑ | LINE/WhatsApp/飞书/钉钉 IM 入站事件已接；Hermes 的 GitHub/API 触发自动化待接 |
| 浏览器自动化 | ◑ | `browser_action` 工具 + `scripts/browser_automation_worker.py`（Playwright，SSRF 防护），默认关闭且按高风险审批 |
| 计算机控制 | ◑ | `computer_action` 工具 + `scripts/computer_control_worker.py`（pyautogui，键鼠/截屏/滚动/快捷键），默认关闭且按高风险审批；桌面端集成待封装 |
| Windows 桌面端 | ◑ | `desktop/` Electron 壳（main/preload/package/README）托管本地 workers 与 IPC；构建发布待验证 | 复用 Web UI，内嵌 OS/回收站/浏览器/计算机/唤醒词 worker |
| 工具自恢复提示 | ✅ | V4A 诊断作为工具结果返回 Agent，`assistant_agent_markdown_preset` 第 12 条指导模型按 no-op/空白差异/零结果/落盘校验诊断修正，不再盲目重试 |
| 审批策略运行时化 | ✅ | approval mining dry-run + `SmartApprovalPolicyService` 运行时自动放行 |
| Docker/podman daemon 危险命令审批门 | ✅ | `contains_dangerous_container_command` + `_smart_approval_allows(tool_input=...)`；特权/宿主网络/根目录挂载等危险容器操作即使免确认也强制确认 |

## 八、目标完成审计（2026-08-13）

逐项核对用户目标（Hermes v0.20 能力复制对齐）：

| 目标项 | 状态 | 证据 |
| --- | --- | --- |
| 流式分句 TTS，边说边生成 | ✅ | `text_to_audio_sentences` + `tts_sentence` SSE + `use-audio.ts` MediaSource 渐进播放；测试覆盖 |
| barge-in：说话即打断，模型感知插入 | ✅ | 四表面录音即 stop TTS/Agent；`stop_chat` 写打断标记；连续语音模式自动发送/自动朗读 |
| 设备端唤醒词 | 形态差异 | Web 无常驻麦克风；以连续语音模式替代 |
| 多 profile 语音路由 | ✅ | `_resolve_voice` + `AppConfig.text_to_speech` 按账号/应用级路由；profile 概念不适配 |
| 全表面 stop | ✅ | Home/WebApp/Debug/公共预览均有 stop；公共预览走 A2A tasks/cancel |
| WhatsApp/Feishu/DingTalk/LINE/QQ/Weixin 语音笔记 | ✅ | 微信闭环；LINE/WhatsApp/飞书/钉钉 webhook；QQ 语音转写适配器；统一 `ImVoiceService` |
| Photon 语音笔记 | 形态差异 | Hermes 私有协议，无对应平台 |
| STT/TTS 独立工具分类 | ✅ | `tts_speak` / `audio_transcribe` |
| 统一语言解析 | ✅ | ASR/TTS `language` 透传；HTTP/工具/前端参数链路 |
| gpt-transcribe 支持 | ✅ | `_resolve_asr_model` + `GPT_TRANSCRIBE_ENABLED` / `GPT_TRANSCRIBE_MODEL` |
| A2A v1.0 插件 | ✅ | Agent Card、message/send、tasks/get、tasks/cancel、message/stream、出站客户端 |
| A2A 与 MCP 分层 | ✅ | MCP=工具池，A2A=Agent 对等通信；实现与文档均区分 |
| Mid-turn redirects | ✅ | 请求级 `set_redirect` / `/subtasks/<id>/redirect` + `_llm_node` 轮前注入 |
| 审批历史挖掘 allowlist | ✅ | `approval_mining` + `/admin/approval-insights` dry-run |
| 审批策略自定义 | ✅ | `tool_governance_policy.require_confirmation=false` 运行时自动放行 |
| 连续拒绝熔断 | ✅ | approval-mining 熔断信号产出 |
| Docker/podman daemon 审批门 | ✅ | 危险容器命令（特权/宿主网络/根目录挂载等）永不自动放行 |
| 工具自恢复 | ✅ | 终端输出回读、patch 已应用检测、落盘校验、搜索零结果探测、自恢复提示词 |
| 上下文压缩 | ✅ | 工具结果裁剪、逐轮微压缩、最近 3 条用户消息保护、ghost-skill 防御 |
| 子代理委派 | ✅ | Redis 化 registry、超时/stall 元数据、`/subtasks` 查询/取消/redirect、execute_code RPC 桥、SSE 实时事件 |

不适配项均有明确产品理由（Web 形态 / Hermes 私有协议），不属于代码缺口。

## 来源

- Hermes v0.20：https://github.com/NousResearch/hermes-agent/releases/tag/v2026.8.3
- 详细功能对比：`docs/research/hermes-agent-v0-20-comparison.md`
- 深度盘点：`docs/research/hermes-v0.20-capability-deep-dive.md`
