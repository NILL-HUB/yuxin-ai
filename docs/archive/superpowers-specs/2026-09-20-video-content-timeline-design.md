# 视频内容时间线设计（形态 A 落地：批次化时间线叙述）

> **状态**：需求已逐项确认，设计已批准，待实现。
> **日期**：2026-09-20
> **主文档**：[02-knowledge-base.md](../../prd/modules/02-knowledge-base.md) | [knowledge-base-product-form-design.md](../../prd/knowledge-base-product-form-design.md)
> **关联文档**：[video-production-p4-design.md](./2026-09-16-video-production-p4-design.md)（KB-P4 出片设计）| [07-public-ai-config.md](../../prd/modules/07-public-ai-config.md)（vision_analyze 绑定 GLM-5.3-Flash）
> **参考调研**：[hypit-and-hyperframes-evaluation.md](../../research/hypit-and-hyperframes-evaluation.md)（非权威）+ Hypit 官方文档（外部）

## 1. 背景与目标

### 1.1 现状问题

知识库视频 L1 解析（`knowledge_media_extractor_service._extract_video`）对**每一帧独立调用**视觉模型：

- 每帧 1 次调用 → 15 帧视频 = 15 次调用，实测 **104s**；
- 帧描述互相独立，**没有上下文连贯性**——模型看不到前后帧，画面描述碎片化；
- 输出是"帧清单"，不是"内容时间线"，无法回答「视频讲了什么、在哪一段」。

### 1.2 形态 A 实测（可行性已验证）

以 stodownload.mp4（73.5s / 15 帧）做对比实测：

| 维度 | 现状（逐帧独立） | 形态 A（多帧批喂 + 时间码） |
|---|---|---|
| 视觉调用次数 | 15 | 2 |
| 耗时 | 104s | 27s |
| 输出 | 每帧孤立描述 | 连贯时间线（含逐句字幕 OCR） |

形态 A = 一次消息塞多帧并标注时间码，让多模态模型（GLM-5.3-Flash，`vision_analyze`）输出连贯内容时间线。

### 1.3 Hypit 参考结论

参考开源项目 Hypit（外部调研，不引入其代码）确认两条设计思想：

1. **台词锚定优先于时间戳锚定**：段落边界 = 台词句（词），删一句台词，挂在它下面的语音/字幕/动画一起走；
2. **时间轴是投影出来的，不是作者写的**：Script 只有词，秒数窗口由 TTS/ASR 对齐后投影生成（`TemporalInstant` / `TemporalWindow`）。

**推论**：时间码一律来自**测量**（ASR cues / 抽帧偏移），**视觉模型不生成时间码**，只描述锚点内容。

### 1.4 目标

把 L1 视频解析从「逐帧独立描述」升级为「**批次化时间线叙述**」：

- 调用次数从 N 降到 N/块，输出连贯、带段落结构；
- 段落 = 台词锚定（有语音/字幕时）或时间片锚定（无语音时）；
- 段落是**编辑挂载点**：KB-P4 阶段的特效/贴纸/转场/字幕可挂载其上随段移动（本次只产出段落结构，不实现元素绑定）；
- 下游（检索 / L2 改细节 / 成片预览）零感知或小幅兼容。

## 2. 已确认的设计决策

| 议题 | 决策 |
| --- | --- |
| 产物形态 | **结构化条目**（每条 = 一个段落），落库为 `MediaSegment` |
| 与现有 L1 关系 | **替换**逐帧独立描述（不再逐帧独立调用） |
| 字幕内容来源 | **ASR 对齐注入**（`speech_text` 来自已有 cues，零模型成本；模型不做画面内字幕 OCR） |
| 时间码来源 | **测量投影**（ASR cues / 抽帧偏移），视觉模型**不输出时间码** |
| 有语音/字幕的视频 | **ASR 句子骨架**：锚点 = 台词句，`window = [start, end]` 投影自 cue |
| 无语音/字幕的视频（如风景） | **均匀时间轴分块**：锚点 = 时间片，`window` = 块区间 |
| 批大小 | 每批 ≈ 10 个锚点（10 句台词 / 10 帧块），块间重叠 1 帧 |
| 输出协议 | 模型返回与锚点一一对应的描述数组 `[{anchor_index, description}]`，时间码由服务端投影 |
| 解析失败 | 该块重试 1 次 → 降级该块内逐帧独立调用（现有逻辑） |

## 3. 架构：按视频类型路由的批次化时间线

改造点集中在 `knowledge_media_extractor_service._extract_video` 的逐帧循环（现有 L270-L309）。抽帧与音轨 ASR 保持不变，新增**路由判定**：

```text
_extract_video（改造后）
├─ 抽帧（不变，ExtractedFrame 带 time_offset）
├─ 音轨 ASR（不变，cues / transcript_segments）
├─ 路由判定：
│    ├─ 有 cues → 场景 B：ASR 句子骨架
│    └─ 无 cues → 场景 A：均匀时间轴分块
├─ 分批批喂视觉模型 → 描述数组（锚点索引对齐）
└─ 投影时间码 → MediaSegment 列表（替换逐帧描述）
```

### 3.1 场景 A：无语音 / 无字幕（风景展示类）

- L1 帧按连续块分组（约 10 帧/块，块间重叠 1 帧保证时间连续性）；
- 提示词要求模型按**画面变化**分段（一个连续画面可合并为一段，不必每帧一段）；
- 锚点 = 时间片，`window` 由服务端按块帧的抽帧偏移投影（首帧偏移 ~ 末帧偏移）。

### 3.2 场景 B：有语音 / 有字幕 / 语音+字幕

- 以 ASR cues（句子）为段落骨架——**台词段就是段落边界**；
- 帧按 cue 的 `[start, end]` 时间范围归组，一批 = 连续约 10 个 cue 区间内的帧；
- 模型只描述画面（不做字幕 OCR），`speech_text` 由 cue 注入；
- 段落对象 = 台词锚定的编辑挂载点：该段的音频、特效、贴纸、转场未来都挂载于此随段移动。

## 4. 结构化条目 Schema

每条目落库为一个 `MediaSegment`（结构不变，下游零感知）：

```json
{
  "content": "画面内容描述（模型输出）",
  "metadata": {
    "media_type": "video",
    "source": "vision_timeline",
    "anchor_type": "speech_sentence | time_slot",
    "anchor_text": "台词句原文（场景 B）或空",
    "start_sec": 3.2,
    "end_sec": 8.7,
    "frame_url": "段落代表帧",
    "speech_text": "台词原文（ASR 注入）"
  }
}
```

要点：

- `start_sec/end_sec` 为**投影窗口**（来自 cue 或分块偏移），非模型生成；
- `frame_url` 取段落代表帧（场景 B 取 cue 区间中点帧，场景 A 取块中点帧）；
- 场景 B 条目保留对原 cue 的 `transcript_segments` 引用（字幕仍由既有 `audio_transcript` 段承载，不重复落库）；
- 兼容：无 `start_sec/end_sec` 的老数据回退读 `time_offset`。

## 5. 批喂与解析

### 5.1 消息结构（每批）

- 系统提示：时间线规格（按锚点描述画面、不做字幕 OCR、输出 JSON 数组）；
- 场景 B：连续 cue 列表（`anchor_index + 台词句 + 时间范围`）+ 该批帧（每帧标注帧序号与时间码）；
- 场景 A：块内帧（带帧序号与时间码）。

### 5.2 输出解析

- 模型返回 JSON 数组 `[{anchor_index, description}]`，按锚点顺序对齐；
- **JSON 解析容错**：解析失败 → 该块重试 1 次 → 仍失败降级为该块内逐帧独立调用（现有逻辑）；
- 描述为空（`strip()` 后空串）的锚点：场景 B 保留仅 `speech_text` 段落，场景 A 跳过该条。

### 5.3 提示词约束

- 明确禁止模型输出时间码（时间码由服务端投影，防止模型编造）；
- 明确禁止模型 OCR 画面内字幕（避免与 ASR 字幕重复）；
- 要求按画面/台词语义分段，保持连续性与叙事性。

## 6. 错误处理与降级

| 故障 | 行为 |
|---|---|
| 某块批喂失败 | 重试 1 次 → 降级该块内逐帧独立调用 |
| 视频无音轨 / ASR 失败 | 场景 A 均匀分块，正常产出 |
| 场景 B 某 cue 区间无帧 | 该台词段跳过画面描述，仅 `speech_text` 段落保留 |
| 整片全失败 | 维持现状 `RuntimeError` |

## 7. 兼容性与接线

| 下游 | 影响 | 处理 |
|---|---|---|
| 知识库检索 | content 仍是描述文本 | 零改动 |
| L2 改细节 | 按命中片段定位区间 | `build_document_l2` 读 `start_sec/end_sec`（无则回退 `time_offset`）参与 `plan_l2_windows` 扩窗 |
| 对话内成片预览 | 消费 ASR 字幕段 + 时间线描述 | 零改动（既有双通道回填） |
| 自动字幕 | `audio_transcript` 段不变 | 零改动 |

> **接线自检**：时间线条目 = `MediaSegment`，复用既有「段落 → 索引」链路；L2 入口为 `POST /space/knowledge-bases/<kb_id>/documents/<document_id>/l2`（既有），仅需适配窗口来源字段。

## 8. 测试策略

- **纯函数单测**：cue→窗口投影、场景 A 分块（重叠）、帧按 cue 归组、`start/end` 投影换算；
- **JSON 解析容错单测**：合法数组 / 非法 JSON / 描述缺失 / 锚点越界；
- **集成真机**：stodownload.mp4（场景 B）+ 构造无音轨视频（场景 A），断言调用次数 = N/块、时间码与 ASR cues 一致、条目含完整 `start/end/speech_text`；
- **全量回归**（既有 5128 用例 + 新增）。

## 9. 范围外（本次不做）

- 特效/贴纸/转场等编辑元素的**绑定与随段移动**（属 KB-P4 编辑功能，本次只产出段落结构）；
- 画面内字幕 OCR 识别；
- 词级（而非句级）锚定；
- Hypit 的 SVML / 渲染管线集成（KB-P4 已决：渲染用 HyperFrames，不引入 Hypit 代码）。
