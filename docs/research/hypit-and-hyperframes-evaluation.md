# Hypit 与 HyperFrames 调研评估

> **非权威**：本文为调研快照，只代表调研当时的结论，**不代表当前实现**。禁止作为判断系统现状的依据。
> **日期**：2026-09-16
> **用途**：为 [视频制作 P4 设计](../superpowers/specs/2026-09-16-video-production-p4-design.md) 提供选型依据

## 1. 结论速览

| 项目 | 是否可集成 | 原因 |
| --- | --- | --- |
| **Hypit** | ❌ 不可 | 许可明确禁止多租户 SaaS 与白标；且交付形态是 Agent Skill 而非可嵌入库 |
| **HyperFrames** | ✅ 可 | HeyGen 开源，**标准 Apache-2.0**，无多租户限制 |

**最终决策**：**不引入 Hypit 任何代码**，仅借鉴其设计思想（语义锚定）；以 **HyperFrames** 作为渲染引擎。

## 2. Hypit

### 2.1 基本情况

| 项 | 实测值（GitHub API） |
| --- | --- |
| 仓库 | `github.com/hypit-ai/hypit` |
| 组织 / 主页 | `hypit-ai` / hypit.ai |
| 创建 / 最近推送 | 2026-07-29 / 2026-09-14 |
| Star / Fork | 957 / 59 |
| 主语言 | TypeScript |
| 依赖栈 | Node 22.12+、pnpm 10.33、TypeScript 5.9（pnpm monorepo） |
| License 字段 | `NOASSERTION`（非标准 SPDX） |

> 媒体称「9 月 7 日开源」，但 GitHub API 显示仓库 **2026-07-29 已创建**。可能当时私有、9/7 转公开，API 无法证实，此处不下结论。

### 2.2 它是什么

核心不是视频生成模型，而是**把视频写成代码的 DSL**（`.svml` 文件）：

```xml
<?svml using="@hypit/markup@1"?>
<svml>
  <import as="seedance" from="@hypit/seedance@1"/>
  <import as="caption"  from="@hypit/caption@1"/>
  <script id="story">
    <ronaldo>
      <HOST>Ronaldo is <D | Dee> tier. || Bro has @hair-gel more ||
            hair gel than @trophy trophies || ...@/trophy@/hair-gel.
    </ronaldo>
  </script>
```

**值得借鉴的设计洞察——语义锚定**：素材绑在**台词**上而非时间轴上。传统剪辑工具绑时间轴，删段音频后字幕/动画仍杵在原位需手动挪；Hypit 中一段台词下挂着语音、字幕、动画，**删掉台词，三样全部自动移除**。改一句话，整条视频自动跟着调。对 Agent 特别友好——读写结构化文本本就是 LLM 强项。

### 2.3 为什么不可集成

**许可证是硬阻断。** GitHub license 字段为 `NOASSERTION`，实为「Hypit Open Source License」（改造版 Apache 2.0 + 附加条件），原文明确：

> **a. Multi-tenant service**：未经 Hypit.AI 书面授权，不得使用 Hypit 源码或其衍生作品**运营多租户环境**，或**将 Hypit 功能作为托管/管理/SaaS 提供给第三方**。
> — *Tenant 定义：一个租户＝一个 workspace。只要环境中有两个及以上**你组织之外**的主体持有各自独立 workspace，即构成多租户服务，**无论是否收费**。*

钰见我是带用户账号、会员套餐、存储配额、分销体系的多租户平台 → **正落在禁止范围内**。

其他两条同样要注意：

- **品牌不可去除**：不得移除 / 修改 Hypit 在 CLI、run reports/manifest、**任何面向用户界面**上的名称/LOGO/版权信息（白标会很别扭）。
- **许可可单方面变更**：贡献者条款写明「生产者可自行决定将开源协议改得更严或更松」——治理风险。

**允许**的：自己跑、单租户、用于本组织工作（含为客户做的工作）。
**禁止**的：对第三方提供多租户服务。

### 2.4 形态上也不适配

| 维度 | Hypit | 钰见我 | 后果 |
| --- | --- | --- | --- |
| 语言/构建 | Node + pnpm monorepo + 自有 CLI | Python + Quart + SQLAlchemy | 无法当库 import，只能当外部进程调 |
| 交付形态 | **Agent Skill**（`npx skills add hypit-ai/hypit -g`） | 后端服务 | 没有「嵌入为 Python 依赖」的官方路径 |
| 运行时依赖 | Live Builds 需 Python 3.10–3.13 + uv + ffmpeg + Chromium | 现有栈 | 要新增一套重量级运行时 |

本质是**给 Coding Agent 用的独立工具链**，不是可嵌入库。

## 3. HyperFrames

### 3.1 归属与许可

| 项 | 值 |
| --- | --- |
| 归属 | **HeyGen, Inc.**（`github.com/heygen-com/hyperframes`） |
| npm 包 | `hyperframes`（bin: `hyperframes`） |
| 许可 | **标准 Apache License 2.0**，纯文本，**无附加条款** |
| 引擎依赖 | puppeteer-core / esbuild / hono（自渲染，非仅封装） |

与 Hypit 的许可对比：

| | Hypit | HyperFrames |
| --- | --- | --- |
| 许可 | 改造版 Apache-2.0 | **标准 Apache-2.0** |
| 多租户 SaaS | ❌ 明确禁止 | ✅ 无限制 |
| 商用/白标 | ❌ 需授权、禁去 LOGO | ✅ 允许 |
| 许可可单方变更 | ⚠️ 有该条款 | 否 |

**结论：可安全用于多租户商业化产品。**

### 3.2 关键能力（实测，非推测）

| 能力 | 属性 | 用途 |
| --- | --- | --- |
| 裁切源素材 | `data-media-start`（Trim offset into source, seconds） | 剪真实素材 |
| 时间轴定位 | `data-start`（秒或 clip ID 引用，如 `"intro + 2"`） | 编排 |
| 片段时长 | `data-duration`（video/audio 默认取媒体时长） | 编排 |
| 多轨叠加 | `data-track-index`（同轨不可重叠） | 画中画 / 字幕轨 |
| 音量 | `data-volume`（0-1） | 配乐 |
| 双画幅 | `data-width` / `data-height`（明确列 1920x1080 与 1080x1920） | 竖横屏 |
| 字幕 | 完整 captions 指南（词级时间戳、逐词样式、语言规则） | 字幕 |
| 变量化重渲染 | `data-composition-variables`（声明数组）+ `--variables`（覆盖对象） | 批量出变体 |
| 子组合 | `data-composition-src` + `data-variable-values` | 模块复用 |

CLI 工作流：`init` → 写 HTML → `lint` → `inspect`（视觉检查文字溢出）→ `preview` → `render`。

渲染选项：`--fps`(24/30/60)、`--quality`(draft/standard/high)、`--format`(mp4/webm 支持透明)、`--workers`、`--gpu`、`--docker`。

**运行时要求**：Node >= 22、FFmpeg、Chromium。

### 3.3 与 Hypit 的关系

Hypit 的渲染后端包 `@hypit/render-hyperframes`，其 `package.json` 依赖 `@hypit/hyperframes`。即 **Hypit 的渲染器本身建立在 HyperFrames 之上**。

这带来一个直接推论：**想走「代码渲染视频」的路线，不必经 Hypit**——HyperFrames 本身就是那层引擎，且许可干净。

## 4. 本仓库现状对照（调研时点）

| 能力 | 状态 |
| --- | --- |
| 视频生成（Seedance/Hailuo/Kling/Vidu，13 个工具） | ✅ provider `atlascloud_video`；但**无助手固定挂载点**，经应用绑定 + 编排选择器调用 |
| 视频分析（抽帧 + 视觉汇总） | ✅ `video_analyze` + `vision_invoke` |
| 音轨 ASR / 关键帧留存 / 视觉向量 / L2 详述 | ✅ P3 已落地 |
| 视频编辑 trim / concat / subtitle | ❌ 完全未实现（代码/YAML/前端/Celery 全 0 命中） |
| 场景切分 / `metadata.time_range` | ❌ 未实现（P4 前置缺口） |
| 抽帧策略 | ⚠️ 固定 3 帧且只取开头（缺陷，见 P4 设计 §5.1） |

## 5. 最终建议

1. **不集成 Hypit**：许可（多租户禁止）+ 形态（Agent Skill ≠ 可嵌入库）双重阻断，且该限制正命中我们的核心用法。
2. **借鉴其设计思想**：「语义锚定」（素材绑台词而非时间轴）对 P4 极有价值，可落在 HTML 容器层级上。
3. **以 HyperFrames 为渲染引擎**：许可干净、能力齐备（`data-media-start` 可剪真实素材、双画幅、字幕、变量化），足以统一「剪辑真实素材」与「代码渲染」两条路径。
4. **若仍要用 Hypit**：必须先获**书面授权**，且只能在**单租户**前提下使用（如仅内部生产或给客户交付），**不得**作为平台功能对用户开放。这需要法务判断。
