# VibeVoice 接入可行性调研

调研日期：2026-08-23

## 结论

**可以接入，但不建议把 VibeVoice 塞进当前 API 主进程，也不建议用它直接替代现有中文连续语音链路。**

更合理的做法是：把 VibeVoice 当作一个**可选的自托管 TTS/ASR 模型服务**，通过
OpenAI 兼容接口挂进现有模型池，保留 SiliconFlow 云服务作为兜底。现有
`/rt-voice` 实时语音会话、Agent 编排、Socket.IO 协议可以不改。

对当前用户的“中文连续语音”场景，VibeVoice-Realtime 0.5B 不是首选，因为它官方只支持英文，
而且模型卡明确说明会向合成音频中嵌入可听见的 AI 声明并添加水印。VibeVoice-TTS 1.5B
虽然支持中英文，但官方已移除 TTS 代码且安装说明被禁用，需要依赖社区封装，风险更高。

## VibeVoice 是什么

VibeVoice 是 Microsoft 开源的语音 AI 模型家族，包含 TTS 与 ASR，仓库与模型均为 MIT 协议。
核心架构是连续语音 tokenizer（acoustic + semantic，7.5 Hz 帧率）+ Qwen2.5 语言模型 +
next-token diffusion 解码头。

官方模型：

| 模型 | 定位 | 官方状态 | 参考来源 |
|---|---|---|---|
| VibeVoice-Realtime-0.5B | 实时流式 TTS，英文为主 | 已开源，可运行 Colab/WebSocket demo | [官方文档](https://github.com/microsoft/VibeVoice/blob/main/docs/vibevoice-realtime-0.5b.md) |
| VibeVoice-TTS-1.5B | 长文本多说话人 TTS，支持中英文 | 官方移除代码、安装说明禁用 | [官方文档](https://github.com/microsoft/VibeVoice/blob/main/docs/vibevoice-tts.md) |
| VibeVoice-ASR | 长音频统一 ASR，50+ 语言 | 已开源，支持 vLLM/Transformers | [官方文档](https://github.com/microsoft/VibeVoice/blob/main/docs/vibevoice-asr.md) |
| VibeVoice-ASR-BitNet | ASR 的 CPU 量化推理引擎 | 已开源，GGUF，1.58 GB | [VibeASR.cpp](https://github.com/microsoft/VibeASR.cpp) |

## 模型规格与运行要求

| 模型 | 权重规模 | 语言 | 关键指标 | 运行要求 |
|---|---|---|---|---|
| VibeVoice-Realtime-0.5B | HF 仓库约 2.0 GB，BF16 参数约 1.0 B | 官方仅英文，实验性多语言语音不含中文 | 首帧约 200-300 ms，8k context，约 10 分钟长文 | 推荐 NVIDIA T4/M4 Pro；wrapper 实测 RTX 3060 约 2 GB VRAM |
| VibeVoice-TTS-1.5B | HF 仓库约 5.4 GB，BF16 参数约 2.7 B | 英文、中文 | 单次最长约 90 分钟，最多 4 个说话人 | 官方代码已移除，社区封装可用 |
| VibeVoice-ASR | HF 仓库约 17.3 GB，BF16 参数约 8.7 B | 50+ 语言，含中文 | 60 分钟单遍处理，Who/When/What 结构化输出 | vLLM 需要较大显存，社区反馈约 32 GB 级别 |
| VibeVoice-ASR-BitNet | 量化后 1.58 GB | 英文、中文等 | 3 线程以上 RTF < 1 | CPU 即可，Windows 需 MinGW/GCC |

数据来源：

- [VibeVoice-Realtime-0.5B 模型卡](https://huggingface.co/microsoft/VibeVoice-Realtime-0.5B)
- [VibeVoice-1.5B 模型卡](https://huggingface.co/microsoft/VibeVoice-1.5B)
- [VibeVoice-ASR 模型卡](https://huggingface.co/microsoft/VibeVoice-ASR)
- [VibeVoice-ASR-BitNet 模型卡](https://huggingface.co/microsoft/VibeVoice-ASR-BitNet)
- [VibeASR.cpp 仓库](https://github.com/microsoft/VibeASR.cpp)

## 与当前项目语音链路的关系

本项目当前语音链路：

- `api/internal/service/realtime_voice_service.py`：Socket.IO `/rt-voice` 会话，能量 VAD、Agent 流、按句 TTS。
- `api/internal/service/audio_service.py`：ASR/TTS 实际调用，目前固定走 `SiliconFlow` 模型池配置。
- `api/internal/extension/realtime_voice_handlers.py`：Socket.IO 命名空间处理器。
- `ui/src/components/RealtimeVoiceDock.vue`：前端语音浮窗。
- `docs/research/realtime-voice-architecture.md`：现有实时语音架构说明。

模型池已经支持 `tts`、`asr` 类型，也有 `model_provider_config.default_base_url`、
`model_key_config` 和 `model_pool_config` 的 provider 抽象，所以新增一个自托管
provider 不需要改数据库结构。

## 可复用的现成封装

社区已经存在 OpenAI 兼容封装，不用从零写：

- `marhensa/vibevoice-realtime-openai-api`：VibeVoice-Realtime 0.5B 的 OpenAI 兼容 TTS 服务，
  提供 `/v1/audio/speech`、`/v1/audio/voices`，Docker/CUDA，约 2 GB VRAM，7 个内置声音，MIT。
  见 [GitHub](https://github.com/marhensa/vibevoice-realtime-openai-api)。
- `tjameswilliams/vibevoice-server`：VibeVoice-ASR-HF 的 OpenAI 兼容 ASR 服务，
  提供 `/v1/audio/transcriptions`，支持 `text/json/verbose_json/srt/vtt`，MIT。
  见 [GitHub](https://github.com/tjameswilliams/vibevoice-server)。
- 官方 vLLM ASR 插件：直接用 `vllm/vllm-openai:v0.14.1` 起服务，OpenAI 兼容
  `/v1/chat/completions`，适合大显存机器。见 [官方文档](https://github.com/microsoft/VibeVoice/blob/main/docs/vibevoice-vllm-asr.md)。
- 官方 WebSocket TTS demo：`demo/web/app.py` 提供 FastAPI `/stream` WebSocket，输出 PCM16，
  可以直接改造成内部 TTS 服务，但不是 OpenAI 兼容。

## 推荐接入方案

### 方案 A：VibeVoice-Realtime 作为可选 TTS provider（推荐先试）

1. 用 `marhensa/vibevoice-realtime-openai-api` 或官方 FastAPI demo 起独立 Docker 服务。
2. 在 `model_provider_config` 增加 `VibeVoice`，`default_base_url` 指向
   `http://vibevoice-tts:8880/v1`。
3. 在 `model_pool_config` 增加一条 `model_type='tts'` 的模型记录。
4. 改造 `AudioService`：把固定 `provider="SiliconFlow"` 改成从模型池按
   `model_type` 解析 provider/base_url/model，并保留现有 SiliconFlow 回退。
5. `RealtimeVoiceService` 不需要改协议，`_speak_agent_stream` 仍然按句调用
   `audio_service._create_tts_response`。

优点：接入成本低，社区 wrapper 已把模型加载、声音别名、MP3/WAV 编码都处理好。

注意：官方 Realtime 只支持英文，内置声音不包含中文；如果继续以中文连续语音为目标，
这个方案只能做英文/中英混合测试，不能直接解决当前“中文回话音色乱、语言不统一”的问题。

### 方案 B：VibeVoice-TTS 1.5B / 7B 作为中文长文 TTS

官方 TTS 支持中英文，但官方仓库在 2025-09 移除了 TTS 代码，安装说明也标记为 Disabled。
社区 wrapper 可以跑，但要自行审计代码、模型下载源、免责声明/水印行为。
适合做播客、长音频生成，不适合作为低延迟连续语音的默认方案。

### 方案 C：VibeVoice-ASR 作为可选 ASR provider

- 大显存机器可用官方 vLLM 插件或 `tjameswilliams/vibevoice-server`。
- 无 GPU 环境可用 `VibeASR.cpp` 跑 BitNet CPU 引擎，1.58 GB，RTF < 1。
- 接入方式与 TTS 相同：增加 provider 和 `model_type='asr'` 模型，`AudioService.audio_to_text`
  改为按 provider 解析。

注意：VibeVoice-ASR 的优势是长音频、说话人分离和 60 分钟单遍处理；对当前几秒到 30 秒的
实时语音片段，这些优势不明显。BitNet 在中文基准 AISHELL-4 的 WER 约 27.45%，比 FunASR
20.41% 和 SenseVoice 22.52% 差，中文短句识别不一定优于现有云 ASR。

### 方案 D：保留现有云服务，只做架构清理

如果目标是解决当前连续语音“音色混乱、语言不统一、任务卡住”的问题，优先动作其实是：

- 统一 TTS 模型，不在同一轮里 MOSS/CosyVoice 反复切换。
- 明确 `language` 参数，避免按句 TTS 时中文/英文混用。
- 修复暂停后无法恢复、识别文本在小语音框重复展示等现有问题。
- 等上述问题稳定后，再把 VibeVoice 作为可切换 provider 加进来做 A/B。

## 具体改动清单

如果按方案 A 落地：

1. `docker/docker-compose.yaml` 增加 `vibevoice-tts` 服务，`--gpus all` 或限制单卡，
   镜像用社区 wrapper 或自建 Dockerfile。
2. `api/internal/service/audio_service.py` 增加通用 provider 解析：
   `LanguageModelService.get_provider_credentials(provider=..., model_type=...)`，
   替换硬编码 `SiliconFlow`。
3. 保留 `_tts_candidates` 和空音频/HTTP 错误回退逻辑，SiliconFlow 仍是默认。
4. `model_provider_config` 增加 VibeVoice provider；`model_pool_config` 增加
   `model_type='tts'` 记录。
5. 实时语音协议不变；前端只把 `voice` 参数映射到 wrapper 支持的声音别名。
6. 补充 `AudioService` 单元测试：provider 解析、base_url 拼接、失败回退、TTS 空音频。

## 风险与限制

- **研究用途限制**：官方 README 和模型卡均写明“不推荐用于商业或真实应用，仅限研究开发”。
  如果本项目要对外提供产品化语音能力，需要先做合规评估。
- **免责声明与水印**：VibeVoice-TTS 和 Realtime 模型卡写明会向合成音频中嵌入可听见的
  AI 声明和不可感知水印，并记录推理请求。这可能直接不满足正常助手语音体验。
- **Realtime 仅英文**：官方只保证英文，实验性多语言语音不含中文，中文输出可能不可预测。
- **中文 TTS 不稳定**：VibeVoice-TTS 官方文档提示中文合成偶发不稳定，建议使用英文标点。
- **依赖冲突**：官方 `pyproject.toml` 需要 `torch`、`transformers==4.51.3`、`diffusers`、
  `numba`、`librosa`、`av`、`aiortc` 等；当前 API 镜像没有这些依赖，不应直接塞进主镜像。
  VibeVoice-ASR-HF 又要求 `transformers>=5.3.0`，与官方 TTS 包要求冲突，必须分服务。
- **硬件限制**：当前机器是 RTX 3070 8 GB，跑 Realtime 0.5B wrapper 约需 2 GB VRAM，
  当前桌面应用已占用约 1.7 GB，基本可行；跑 1.5B/7B 长文 TTS 或完整 ASR 会很紧张。
- **社区 wrapper 维护风险**：第三方封装更新速度、依赖版本、模型下载源需要锁定版本并审计。

## 结论

VibeVoice 可以“拉进来改一改”，但正确的改法是**独立自托管服务 + 模型池 provider +
保留云兜底**，而不是把它的 Python 代码并入 API 容器。当前中文连续语音优先继续用
SiliconFlow/CosyVoice 方案并修复已有稳定性问题；VibeVoice 更适合作为自托管实验选项，
先验证英文实时 TTS，再根据需求评估中文 TTS 或 BitNet CPU ASR。
