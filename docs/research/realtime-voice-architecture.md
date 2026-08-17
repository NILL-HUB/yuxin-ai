# 实时语音助手架构（Realtime Voice Assistant）

## 目标

在首页聊天框旁提供可嵌入的实时语音助手：开启后进入连续语音对话，
用户可以用语音驱动辅助 Agent 完成任务，支持开口打断、暂停、停止等控制。

## 方案选型

### LouChat / LobeChat 调研结论

用户提到的 “LouChat” 未检索到独立成熟项目，最接近的是开源项目 **LobeChat**
（`lobehub/lobe-chat`）。LobeChat 定位是聊天客户端/前端框架，具备 TTS/STT、
插件与 Agent market，但：

- 它是完整的产品 UI，而不是可嵌入现有项目消息流/任务系统的实时语音 SDK；
- 其语音交互主要是“录音/上传 → STT → LLM → TTS”的环节组合，
  不是 ChatGPT Voice 级别的语音到语音实时双工；
- 本项目已有完整的模型池、Agent 编排、工具确认与消息持久化，
  整体替换为 LobeChat 会引入重复架构。

结论：**不整体替换**，在本项目内自建实时语音会话通道，复用现有 Agent 与模型池。

### 实现路径

当前环境没有 OpenAI Realtime 模型/Key，因此采用现有基础设施自建：

- 传输：项目已有的 Quart + python-socketio AsyncServer，新增 `/rt-voice` 命名空间；
- 上行：浏览器 `getUserMedia` 采集 → 16kHz 单声道 Int16 PCM → Socket.IO 二进制帧；
- VAD：服务端能量 VAD，检测到约 850ms 停顿后冻结当前语音段；
- ASR：复用模型池 `SiliconFlow + TeleAI/TeleSpeechASR`；
- Agent：复用首页辅助 Agent 的流式会话链路（任务、工具确认、记忆一致）；
- TTS：按句调用模型池 `SiliconFlow + fnlp/MOSS-TTSD-v0.5`，逐句回传音频；
- TTS 质量：先清洗 Markdown/Emoji/表格等不适合朗读的内容；
  长文本优先 CosyVoice2（音色稳定），短文本自动回退 MOSS；
- 打断：客户端检测到用户开口时发送 `rt.barge`，服务端取消当前 Agent/TTS；
- 语音控制：转写命中“停止/暂停”等控制词时直接停止当前任务。

语音回合会实时同步到主对话：转写完成后在首页消息流中创建人类消息，
Agent 的流式回答/工具进度通过 `rt.stream` 事件直接驱动主聊天区，
小语音框只保留状态，不重复展示识别文本。

## 协议

命名空间：`/rt-voice`（握手时携带 JWT，路径经 nginx `/socket.io` 代理）。

客户端 → 服务端：

- `rt.start`：初始化会话（`sample_rate`）
- `rt.audio`：16kHz 单声道 Int16 PCM 二进制帧
- `rt.barge`：开口打断当前 Agent/TTS
- `rt.pause` / `rt.resume`：暂停 / 恢复聆听
- `rt.stop`：停止当前任务

服务端 → 客户端：

- `rt.state`：`listening / transcribing / thinking / speaking / paused`
- `rt.transcript`：最终转写文本
- `rt.agent`：Agent 流式回答增量
- `rt.stream`：原始 Agent SSE 事件（驱动主对话流式渲染）
- `rt.audio`：逐句 TTS 音频（base64 MP3）
- `rt.control` / `rt.error`

## 关键文件

- 后端会话与编排：`api/internal/service/realtime_voice_service.py`
- Socket.IO 命名空间：`api/internal/extension/realtime_voice_handlers.py`
- 前端组件：`ui/src/components/RealtimeVoiceDock.vue`
- 首页接入：`ui/src/views/pages/HomeView.vue`

## 后续演进

若未来接入 OpenAI Realtime API 或 LiveKit Agents，可把 `/rt-voice`
传输层替换为 WebRTC/实时模型通道，会话状态、打断与控制协议保持不变。
