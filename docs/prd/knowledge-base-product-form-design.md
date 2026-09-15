# 知识库核心产品形态设计

> **状态**：P1 数据基座、P2A 多模态素材入库、P2B 分片上传、P3 检索与视觉向量均已完成（见 §9.2），P4–P5 为设计稿（待实施）｜**版本**：v1.3｜**日期**：2026-09-15
> **定位**：把「知识库」从文本文档 RAG 库补足为**全媒体素材中心 + 内容取料台 + 容量商业化**的完整产品形态。
> **上游依据**：[product-vision.md](./product-vision.md) 产品承诺（L2 能力层"存所有文件（含视频素材）；做视频时讨论细节→自翻素材→出片预览→改"）。
> **现状基线**：[modules/02-knowledge-base.md](./modules/02-knowledge-base.md)（双层知识库设计）。
> **相关模块**：[modules/06-file-storage.md](./modules/06-file-storage.md)｜[modules/07-public-ai-config.md](./modules/07-public-ai-config.md)｜[modules/04-social-creator.md](./modules/04-social-creator.md)

---

## 一、问题与定位

### 1.1 当前落差

`product-vision.md` 对知识库承诺的是**全媒体素材中心 + 视频制作闭环**；立项时落地状态表中视频素材标注为「⚠️ 半可用 —— 仅存储，不解析/不抽帧/不入库」（该标注已由 P2A/P2B/P3 消除，现为「✅ 真可用」）。代码核实后的真实落差：

> **注**：下表是**设计立项时的现状基线快照**。其中「媒体类型 / 内容理解 / 组织方式 / 容量 / 大文件」五项落差已由 P1 + P2A + P2B 解决（见 §9.2），保留此表仅用于说明起点。

| 维度 | 产品承诺 | 代码现状（立项时基线） | 现状（P2B 后） |
| --- | --- | --- | --- |
| 媒体类型 | 文档 + 图片 + 视频 + 音频 | 仅文档可解析入库；图片层允许上传但不解析；**音视频不在上传白名单** | ✅ 已解决（P2A：音视频白名单 + 类型硬约束 + 多模态解析） |
| 内容理解 | 素材可被语义检索 | 多模态能力（抽帧/OCR/ASR）**存在但独立于知识库**，产物用完即弃 | ✅ 已解决（P2A：产物写 Segment 并向量化） |
| 组织方式 | 按项目/类型/时间可管理 | 仅扁平 `KnowledgeBase`，无分类、无分区、无知识库级标签 | ✅ 已解决（P1：`base_type` + 两级分区 + 知识库标签） |
| 容量 | — | **存储配额能力完全空白**，上传仅 15MB 单文件上限 | ✅ 已解决（P1 配额体系 + P2B 分片上传解除上限，上限按套餐分级） |
| 大文件 | 视频素材动辄数 GB | `UploadFile.size` 为 `Integer`（上限约 2.1GB），**必然溢出** | ✅ 已解决（P1 `BigInteger` + P2B 分片流式合并） |

### 1.2 定位修正

> **知识库 = 小钰的「素材后勤仓 + 内容取料台」**，同时保留用户手动管理入口。

知识库是**双入口**系统，不是把用户赶出去：

| 入口 | 使用者 | 场景 |
| --- | --- | --- |
| **对话框（主入口）** | 小钰代理执行 | 「帮我从电脑把视频传进去」「自翻素材」「改细节」 |
| **知识库页面（托管入口）** | 用户手动 | 自己上传、整理、删除、查看解析结果 |

两个入口操作**同一份数据**，权限与配额一致。用户"让小钰帮传"和"自己传"是同一件事的两条路径，不是两套系统。

### 1.3 场景链路与知识库触点

```text
收到需求  →  讨论细节  →  【自翻素材】  →  出片预览  →  【改细节】
   对话框      对话框          ↑知识库         对话框         ↑知识库
                          (检索取料)                    (定位修改点)

旁路：用户手动上传 / 让小钰从本机帮传  →  【素材入库】  →  分级解析  →  可被检索
```

- **素材入库是独立旁路**：与制作链路解耦，随时可入，入库即触发分级解析
- **只有「自翻素材」与「改细节」两个环节触碰知识库**；「出片预览」等成品展示在对话框内完成
- **出片产物不自动入知识库**（除非用户显式要求存档）

### 1.4 四条能力线

| 能力线 | 定位 | 优先级 |
| --- | --- | --- |
| **全媒体素材中心** | 文档/图片/视频/音频统一入库、深度解析、可检索 | 🔴 核心 |
| **内容取料台** | 板块 + 分区 + 标签三轴组织，小钰精准取料 | 🔴 核心 |
| **知识资产沉淀** | 分类/标签/版本/引用追踪（复用现有能力） | 🟡 支撑 |
| **容量与商业化** | 分层配额 + 付费扩容 + 上传前校验 | 🔴 硬约束 |

### 1.5 产品边界

延续 [04-social-creator.md §18.5](./modules/04-social-creator.md) 已确立原则：**记忆和知识库是用户私有能力，绝不进入社区**。素材库私有，只有用户主动发布并审核通过的成品才公开展示。

---

## 二、数据模型设计

### 2.1 模型总览

```text
KnowledgeBase（板块/项目，语义升级，不新建表）
  ├── base_type:      document / image / video / audio / mixed   [新增]
  ├── partition_mode: none / date_month / date_day / custom      [新增]
  ├── project_id                                                 [不采用，见 2.2]
  └── 沿用 name / description / knowledge_scope / owner_account_id
        / visibility_scope / settings / embedding_model_id

KnowledgePartition（新增：分区，两层树）
  id / knowledge_base_id / name / partition_key
  parent_id / sort_order / visibility_scope(预留) / created_at

KnowledgeDocument（素材）
  ├── partition_id    [新增]
  ├── media_type      [新增] document / image / video / audio
  └── parse_profile   [新增 JSONB] 记录解析档位与产物索引

KnowledgeBaseTag / KnowledgeDocumentTag（新增：标签关联）
  knowledge_base_id | knowledge_document_id + tag_id + account_id

account_storage_usage（新增：容量计量）
  account_id / used_bytes / updated_at

VideoVisualEmbedding（P3 已落地：关键帧视觉向量）
  account_id / knowledge_base_id / knowledge_document_id / segment_id（唯一）
  frame_url / scene_index / model_id / embedding(Vector(1536))
```

### 2.2 为什么 `KnowledgeBase` 即「板块」，不另建 Project

用户诉求「用户和 agent 可以创建一个个不同的知识库，等于一个个不同的项目，例如文档库/图片库/视频库」表明：**「项目」与「知识库」是同一层语义**（按类型分或按项目分，都是板块的不同组织意图），不需要两个层级。

- 另建 `Project` 会形成 `Project → KnowledgeBase → Document` 三层，实际语义只需两层
- 直接用 `KnowledgeBase` 承载，可**零成本复用**全部既有能力：`knowledge_scope` 作用域、`layered_search` 分层检索、`create_knowledge_retrieval_tool` 检索工具、现有权限体系

### 2.3 板块类型（硬约束）

| base_type | 允许的媒体类型 | 拒绝行为 |
| --- | --- | --- |
| `document` | 文档类（md/doc/docx/pdf/txt/csv/xlsx/html 等） | 图片/音视频 → 服务端拒绝 |
| `image` | 图片类（jpg/jpeg/png/webp/gif/svg） | 文档/音视频 → 服务端拒绝 |
| `video` | 视频类（mp4/mov/avi/mkv/webm） | 文档/图片/音频 → 服务端拒绝 |
| `audio` | 音频类（mp3/wav/m4a/aac/flac） | 文档/图片/视频 → 服务端拒绝 |
| `mixed` | 不限 | 兼容存量库 |

**类型校验在服务端强制**（非前端提示），保证「图片库全是图片」由表结构约束保证，不依赖用户自觉。存量 `KnowledgeBase` 默认迁移为 `mixed`。

### 2.4 两级分区体系

`partition_mode` 定义分区的产生方式：

| 模式 | 行为 |
| --- | --- |
| `none` | 不分分区，素材平铺（适合小库） |
| `date_month` | 上传自动归入 `2026-09`，系统按需自动建分区 |
| `date_day` | 上传自动归入 `2026-09-12` |
| `custom` | 用户/小钰手动建命名分区（如「春季新品」），可改名、移动素材 |

**层级限制：首版两层（大类 / 子类），服务端强制校验。**

- 两层覆盖多数真实需求（产品→子类、系列→单集、用途→细类）
- 避免深树带来的 UI 混乱与小钰导航决策复杂化
- `parent_id` 结构天然支持更深深层，未来放开不需改表
- **需实现防成环校验 + 路径维护**，防止移动节点产生孤儿

**分区权限：首版不做**。分区是组织手段而非权限边界，权限仍在板块层。`KnowledgePartition` **已落地 `visibility_scope` 字段**（默认继承板块可见性，P1 实现），未来若上团队协作，加 `owner_account_id` 即可放开，结构上不阻塞。

**分区 vs 标签的分工**（设计上必须区分）：

| 维度 | 分区（Partition） | 标签（Tag） |
| --- | --- | --- |
| 归属关系 | **互斥** —— 一个素材只能在一个分区 | **多重** —— 一个素材可有多个标签 |
| 结构 | 层级（两层树） | 平铺 |
| 表达 | "这个素材**属于**哪里" | "这个素材**具备**什么属性" |
| 示例 | 产品A / 功能演示 | 4K、竖屏、户外、新品 |

判断法则：互斥层级归类 → 分区；可交叉叠加属性 → 标签；按时间切片 → 日期分区。**不做多维交叉用分区**（会组合爆炸），此时标签才是正解。

### 2.5 标签体系（复用现有）

复用 [tag.py](../../api/internal/model/tag.py) 的 `Tag` 模型（`account_id/name/description/tag_type/status`）与 [tag_assignment_service.py](../../api/internal/service/tag_assignment_service.py) 的关键词 + LLM 自动打标能力，仅把作用对象从 App/Workflow 扩展到知识库：

- 新增 `KnowledgeBaseTag` / `KnowledgeDocumentTag` 关联表（对齐既有 `AppTag` / `WorkflowTag` 模式）
- 板块级标签用于**跨板块索引导航**；素材级标签用于**属性过滤**
- 支持自动打标（复用现有服务）与手动打标

### 2.6 容量配额模型

按已确认的分层策略：

| 用户类型 | 存储配额 | 配置方式 |
| --- | --- | --- |
| 注册用户 | **5 GB** | 系统默认基线 |
| 普通会员 | **100 GB** | 套餐权益 `storage_quota_gb` |
| 高级会员 | **500 GB** | 套餐权益 `storage_quota_gb` |
| 扩展包 | **累加** | 单独购买，叠加在套餐配额之上 |

**配额计算**：

```text
total_quota = max(基线 5GB, 当前生效套餐的 storage_quota_gb) + sum(已购扩展包 GB)
used_bytes  = account_storage_usage.used_bytes   （由上传/删除事件维护）
```

**为什么用 `PlanEntitlement` 而不给 `Plan` 加列**：

`PlanEntitlement`（[billing.py L69-L94](../../api/internal/model/billing.py)）是 `plan_id + feature_key + feature_value + value_type` 的自由键值表，`parsed_value` 已支持 number/decimal/boolean/json 解析。

- 管理员在会员套餐板块**新增 feature_key `storage_quota_gb` 即生效**，不改表结构、不改代码
- 完全符合「套餐可以在会员套餐板块管理员创建即可」
- 未来扩展「并发任务数」「单文件上限」等权益，同一机制承载

**扩展包**：作为 `Plan.plan_type = 'storage_addon'` 的一种套餐类型，复用现有 `PurchaseOrder`（支持 `balance / wechat / alipay`）与 `BalanceAccount` 扣款链路。

**计量策略**：

- `UploadFile` 已含 `size` + `account_id`，可作为计算源
- 新增轻量 `account_storage_usage` 表**缓存 `used_bytes`**，避免每次上传都全表 `sum(upload_file.size)`
- 上传/删除/回收站清理/物理销毁时同步增减

**计入范围**：**凡是占用存储的都计入配额**——原视频 + 解析衍生品（关键帧、缩略图）一律计入。理由：配额是固定容量空间的占用，用户心智就是"我占了多少空间"，1GB 视频解析后占 1.2GB 即计 1.2GB，公平且无需额外解释。

**平台侧保护**：单素材解析产物体积设硬上限（**建议 ≤ 原文件 20%**），防止抽帧密度等配置失误或异常素材导致衍生品体积失控，意外打爆用户配额。这是平台对自身的约束，不是对用户的计费策略。

---

## 三、多模态解析设计

### 3.1 复用已有能力，做"接线"而非"造轮子"

关键发现：所需多模态能力**大部分已存在**，只是独立于知识库、用完即弃。

| 能力 | 现有实现 | 现状 |
| --- | --- | --- |
| 视频抽帧 + 视觉理解 | [video_analyze.py](../../api/internal/core/tools/builtin_tools/providers/vision_tools/video_analyze.py)（ffmpeg 抽帧，SSRF 防护，50MB 上限） | 内置工具 + 共享视觉模块，视频素材已接入索引（P2A） |
| 图片 OCR + 视觉理解 | [vision_analyze.py](../../api/internal/core/tools/builtin_tools/providers/vision_tools/vision_analyze.py) | 内置工具 + 共享视觉模块，图片素材已接入索引（P2A） |
| 音频 ASR | [audio_service.py](../../api/internal/service/audio_service.py)（SiliconFlow，TeleSpeechASR / whisper-large-v3） | 服务已就绪，音频素材已接入索引（P2A） |
| 文生视频 | [atlascloud_video](../../api/internal/core/tools/builtin_tools/providers/atlascloud_video)（seedance 2.0 / hailuo 2.3 / kling o3 / vidu q3 turbo） | 已具备（下游内容生成用） |

**要做的是把产物从"用完即弃"改为"写入 Segment + 向量化"**。

### 3.2 解析产物落点

**核心设计选择：文本类产物直接落 `KnowledgeSegment`，不新建媒体表。**

| 产物 | 形态 | 存放位置 | 入向量库 | 计配额 |
| --- | --- | --- | --- | --- |
| 原素材 | 文件 | 对象存储 + `UploadFile` | ❌ | ✅ |
| ASR 转写 | 文本 + 时间戳 | `KnowledgeSegment.content` | ✅ | ❌ |
| 视觉描述 | 文本（每场景一段） | `KnowledgeSegment.content` | ✅ | ❌ |
| OCR 文本 | 文本 | `KnowledgeSegment.content` | ✅ | ❌ |
| 场景切分 | JSON（序号 + 起止时间） | `KnowledgeSegment.metadata` | ❌ | ❌ |
| 关键帧 | 图片文件（JPEG 压缩） | 对象存储 + `UploadFile` | 文本描述 ✅ / 视觉向量 ✅ | ❌（解析中间产物，见 §3.4） |
| 缩略图 / 封面 | 小图 | 对象存储 | ❌ | ✅（体积极小） |

> **落地实况**：已落地「ASR 转写 / 视觉描述 / OCR 文本 → `KnowledgeSegment.content`（入文本向量库）」，即上表中"入向量库"的**文本侧**已通。视频关键帧现已**留存为 `UploadFile`**（`frame_url` 写入帧片段 `metadata`），使视觉向量可后补而不必重跑解析；**视觉向量索引已建立**（P3：`video_visual_embedding` 表 + `VisualEmbeddingService`，见 §3.4 与 [modules/02-knowledge-base.md §11.10](./modules/02-knowledge-base.md#1110-关键帧视觉向量p3-已落地)）。场景切分的 `time_range` 仍未写入 `metadata`（视频帧片段当前 `metadata` 为 `media_type` / `scene_index` / `frame_count` / `frame_url`）。

**为什么产物即 Segment**：

- 向量索引（`knowledge_segment_embedding_{dim}`）、hybrid 检索、rerank、`layered_search` 五层作用域**全部零改造复用**
- 「改细节」定位靠 `metadata.time_range` / `frame_urls`，无需额外模型
- 文本文档与视频场景处于**同一语义空间**，天然可按语义混排

### 3.3 分级混合解析

`KnowledgeDocument.parse_profile` 记录双阶段状态：

```text
L1 基础解析（上传即自动触发）  → 目标：素材"能被找到"
L2 深度解析（按需 / 后台空闲） → 目标：素材"能被精细修改"
```

| 媒体类型 | L1（上传即跑） | L2（按需/后台） |
| --- | --- | --- |
| 文档 | 现有链路：parsing → splitting → indexing → completed | 无（已完备） |
| 图片 | OCR + 视觉摘要 → 1 Segment | 细粒度 OCR 区块坐标、多图关联 |
| 短音频（≤5min） | ASR 全文转写 → 1 Segment | 说话人切分、情绪标注 |
| 长音频（>5min） | ASR 全文转写 → 1 Segment | 说话人切分、章节切分 |
| 视频 | 音轨 ASR 转写 + 关键帧抽取 + 视觉描述 → 每帧 1 Segment | 逐场景视觉详述、精细时间轴、说话人切分 |

> **L1 落地实况**：图片（视觉摘要 + OCR）、音频（ASR 全文转写）已按上表落地。视频 L1 已实现「音轨 ASR 转写 + 关键帧抽取 + 视觉描述」并留存关键帧（`frame_url`），设计稿中的"场景粗切分"未落地。上表描述的是目标档位划分，非当前实现清单。
>
> **L2 落地实况（P3）**：视频 L2 的「逐场景视觉详述」已落地，落点见 §3.4 与 [modules/02-knowledge-base.md §11.11](./modules/02-knowledge-base.md#1111-l2-按需解析p3-已落地)：由 Celery 任务 `internal.task.knowledge_l2_tasks.build_document_l2_task` **按需触发**（不加 beat），状态写入 `parse_profile.tier2`，**回写同一批 Segment 的 content/metadata，不新建 Segment**。仍未实现：精细时间轴、说话人切分、图片细粒度 OCR 区块坐标、多图关联。

**要点**：

- **L1 必跑且优先**：自翻素材的刚需是"先能找到"，关键帧 + ASR 即最小可用集
- **L2 控成本**：长视频视觉详述最贵，仅在检索命中、用户显式要求、或后台空闲时触发
- **L2 回填同一批 Segment**（补充 `content` 与 `metadata`），**不新建 Segment**，避免重复
- 状态机在现有 `waiting/parsing/splitting/indexing/completed/error` 之上扩展 `tier1_*` / `tier2_*` 双阶段标记

### 3.4 关键帧视觉向量索引

按决策纳入。除「视觉描述文本」入文本向量库外，关键帧本身经视觉编码模型（CLIP 类）生成视觉向量，独立建索引，支撑**以图搜图**。

| 项 | 说明 |
| --- | --- |
| 存储 | `VideoVisualEmbedding` 独立表（视觉向量维度与文本 embedding 不同，不复用 `knowledge_segment_embedding_{dim}`） |
| 模型 | 模型池新增模型类型 `visual_embedding`（`ModelType.VISUAL_EMBEDDING`，视觉编码，无上下文窗口概念）；选型为硅基流动 `Qwen/Qwen3-VL-Embedding-8B`（文本/图片共享语义空间），维度固定 `1536`（原生 4096 经 MRL 降维，受 pgvector 上限 2000 约束）。该类型**不注册进 langchain `model_class_registry`**——其 REST 入参与 `OpenAIEmbeddings` 不兼容，注册会导致静默只编码文本，改为独立 HTTP 调用 |
| 检索 | **同一语义空间，无需融合排序**（原设计假设的"两个独立空间"经实测修正）：Qwen3-VL-Embedding 把文本、图片、视频映射到同一语义空间，因此文本 query 可直接与库内图片向量比对余弦相似度；`VisualEmbeddingService.search_by_text` / `search_by_image` 共用同一套排序逻辑。检索为**并行的补充召回通道**，与文本向量召回结果由上层合并 |
| 计费 | 每帧多一次编码调用 + 多一份向量存储；视觉编码走独立模型凭证（`get_provider_credentials(model_type="visual_embedding")`） |
| 与文本检索关系 | 语义检索主路径仍走文本向量（`knowledge_segment_embedding_{dim}`）；视觉向量是并行的补充召回通道 |

**解析链路要求（已落地）**：关键帧生成后同时留存帧文件与 `parse_profile.frames`（含 `segment_id` / `frame_url` / `scene_index`），即使 L2 未跑，帧文件也在，保证视觉向量可后补而不必重跑解析。

**关键帧留存不计用户存储配额**：帧是解析中间产物（随素材删除），当前实现不调用 `add_usage`；因此它不占用 §2.6 的配额额度。若后续要计入，需在 `_persist_frame` 后配对 `add_usage` 与 `purge_knowledge_document` 的 `release_usage`。

> **落地实况（P3 已完成）**：帧文件留存 —— 每帧上传为 `UploadFile`，其对象 key 作为 `frame_url` 写入该帧片段的 `metadata`（未留存/留存失败时为空字符串）；`parse_profile.frames` 汇总已写入；`video_visual_embedding` 表（含 HNSW 余弦索引）与 `VisualEmbeddingService` 已落地，解析链路在写完文本向量后自动为带 `frame_url` 的帧片段建立视觉向量索引（重解析前先清空旧向量，保证幂等）。**读取侧**已接入检索主链路：`RetrievalService._visual_recall_knowledge_base` 在 `semantic`/`hybrid` 策略下并行补充视觉召回，按 `segment_id` 去重合并、受同一套过滤约束（分区/媒体类型/标签/阈值），并在 `has_vectors()` 预检为否时不发起编码调用以控成本（此前只写不读，已修正）。视觉检索当前在服务层按余弦相似度排序（每视频数帧，量级可控）；若单库帧数显著增长，可改为 SQL 侧 pgvector 查询（表已建 HNSW 索引）。

---

## 四、取料链路设计

### 4.1 链路 A：自翻素材（广搜）

```text
用户描述需求（"做个新品介绍视频"）
  → 小钰提取检索意图（主题 / 风格 / 场景 / 情绪 / 时长偏好）
  → 确定检索范围：当前板块 / 分区优先 → 不足时按标签 + 语义跨板块扩展
  → 检索：layered_search（五层作用域） + tag filter + media_type filter + partition 范围
  → 召回按类型分组：视频场景 / 图片 / 文档段落
  → 返回候选素材（带缩略图 / 时间戳 / 摘要）
  → 候选列表在对话框内展示，用户点选或让小钰自动选
```

### 4.2 链路 B：改细节（精确定位）

```text
用户："把第 3 个视频讲产品卖点那段改一下"
  → 小钰定位 Segment：靠 metadata.time_range 命中 00:02:15 - 00:03:40
  → 取出该片段上下文：ASR 文本 + 视觉描述 + 关键帧
  → 执行修改（重新生成旁白 / 裁剪片段 / 替换画面 / 加字幕）
  → 结果在对话框预览
```

**两条链路差异**：自翻素材是**广搜**（召回多候选），改细节是**精确定位**（找到确切片段）。两者都依赖 Segment 的 `metadata` 承载时间轴——这是 §3.2 选择"产物落 Segment"的根本原因。

### 4.3 树状分区对 Agent 检索的价值

分层分区对**人类**是组织便利，对 **Agent 是确定性的导航骨架**：

```text
小钰的渐进式检索：
  第 1 层：产品类还是场景类素材？   → 选集
  第 2 层：哪个产品 / 系列？         → 选子树
  第 3 层：哪个方面 / 单集？         → 命中分区
  → 在最终分区范围内做语义检索
```

面对数百个平铺分区时，小钰只能靠 LLM 猜哪个相关，易跑偏；有树则可**确定性下钻**，显著降低幻觉、减少无效召回、节省 token。

---

## 五、视频能力设计

### 5.1 现状核实

| 能力 | 现状 |
| --- | --- |
| 文生视频 | ✅ 已有 4 模型（seedance 2.0 / hailuo 2.3 / kling o3 / vidu q3 turbo） |
| 视频分析抽帧 | ✅ 已有 `video_analyze.py` |
| 视频剪辑 / 拼接 / 合成 | ❌ **完全没有**（ffmpeg 仅用于抽帧，无 `concat` / `trim` / 时间轴实现） |

### 5.2 纳入范围：轻量剪辑三件套

按决策纳入**裁剪 + 拼接 + 加字幕**三件套，覆盖多数「改细节」刚需。

| 能力 | 实现方式 | 说明 |
| --- | --- | --- |
| 裁剪（trim） | ffmpeg 封装，按 `metadata.time_range` 切分 | 支持单段/多段裁剪 |
| 拼接（concat / merge） | ffmpeg concat demuxer | 同编码参数素材直接拼接 |
| 加字幕 | ffmpeg 字幕烧录（ASR 产物直接复用） | 字幕源来自 Segment 的 ASR 文本 + 时间戳 |

**设计约束**：

- **不做时间轴 UI**：产物由对话框预览，避免引入专业剪辑前端
- **不做转场 / 特效 / 多轨音画**：留给独立项目
- **转码是 CPU 密集**：需专门任务队列（Celery）+ 独立配额计量，避免阻塞主链路
- 产物默认不入知识库，用户显式要求才存档

---

## 六、配额校验收口

```text
所有上传路径
  ├─ 用户页面手动上传
  ├─ 小钰从本机帮传（desktop bridge）
  └─ 外部数据源同步（Celery，飞书 / Notion / GitHub / 本地文件夹）
       ↓
  统一经 StorageQuotaService.check(account_id, incoming_bytes)
       ↓
  used_bytes + incoming_bytes > total_quota  →  拒绝 + 引导扩容
       ↓
  通过 → 落库 + account_storage_usage.used_bytes 累加
```

**关键：外部数据源同步必须校验**，否则用户可经同步绕过配额。所有路径统一收口到一处，禁止各入口自行判断。

---

## 七、交互设计

### 7.1 入口 A：对话框（主入口）

| 用户说 | 小钰行为 |
| --- | --- |
| "帮我把 D 盘那个视频传到视频素材库" | 走桌面端本机文件能力读取 → 经 `StorageQuotaService` 校验 → 上传 → 触发分级解析 |
| "做个新品介绍视频" | 自翻素材 → 出片 → 对话框预览 → 迭代改细节 |
| "帮我建一个视频素材库，按月分区" | 调 `create_knowledge_base` 工具创建板块（含 `base_type` / `partition_mode`） |
| "我视频库快满了吗" | 查用量，返回「已用 82 / 100 GB」 |

### 7.2 入口 B：知识库页面（托管入口）

| 页面 | 能力 |
| --- | --- |
| 板块列表 | 创建板块（选类型 + 分区模式）、查看用量、跳转详情 |
| 板块详情 | 分区树导航、素材网格（缩略图）、上传、删除、标签管理 |
| 素材详情 | 预览（视频可播放）、查看解析产物（ASR 文本 / 时间轴 / 关键帧）、重新解析、编辑标签 |
| 用量面板 | 「已用 X / 总量 Y GB」，含扩容入口 |

### 7.3 一致性要求

两入口操作**同一份数据、同一套配额校验**。小钰帮传与用户自传走**同一个上传服务**，配额校验收口在一处。

### 7.4 Agent 工具需求

| 工具 | 用途 | 状态 |
| --- | --- | --- |
| `create_knowledge_base` | 参数含 `name` / `base_type` / `partition_mode` / `description`，支持对话内建库 | ✅ **已落地**（builtin provider `knowledge_base_tools`，见下） |
| 检索工具扩展（改造 `search_knowledge_base`） | 新增 `partition_id` / `media_types` / `tags` / `score_threshold` 四个可选过滤参数 | ✅ **已落地**（P3，见 [modules/02-knowledge-base.md §11.9.3](./modules/02-knowledge-base.md#1193-检索工具的四个可选入参)） |
| 视频轻量编辑工具（新增） | `video_trim` / `video_concat` / `video_subtitle` | ⬜ 规划（P4） |

`create_knowledge_base` 已实现的边界（照实描述，不含未落地能力）：

- 位置：`api/internal/core/tools/builtin_tools/providers/knowledge_base_tools/`（provider 在 `providers.yaml` 登记，category 为 `tool`）。
- 参数：`name`（必填）、`base_type`（可选，`document`/`image`/`video`/`audio`/`mixed`，默认 `mixed`）、`partition_mode`（可选，`none`/`date_month`/`date_day`/`custom`，默认 `none`）、`description`（可选）。`base_type` / `partition_mode` 在工具内先做枚举校验，非法值直接返回可读错误，不进入服务层。
- 服务调用：`KnowledgeBaseService.create_user_content_base(..., operation_context="user")`，仅创建**当前登录用户的私有**用户资料库。
- 账号来源：由运行时挂载点 [assistant_agent_service.py](../../api/internal/service/assistant_agent_service.py) 的 `_build_assistant_runtime_tools` 通过工厂参数 `account_id` 透传（与 `os_file_task` / `computer_action` 的 `requester` 同一注入点），工具内部再经 `AccountService` 加载真实 `Account` 实例。
- **未落地**：视频轻量编辑工具仍为规划项（P4）。检索过滤参数扩展已在 P3 落地（见 §7.4 表与 [modules/02-knowledge-base.md §11.9](./modules/02-knowledge-base.md#119-检索过滤参数p3-已落地)）。

---

## 八、必须同步修复的现有缺陷

| # | 缺陷 | 现状 | 修复方案 | P1 状态 |
| --- | --- | --- | --- | --- |
| 1 | **`UploadFile.size` 溢出** | `Integer`，上限约 2.1GB | 升级 `BigInteger`（必改，否则大视频写坏） | ✅ 已修复 |
| 2 | **单文件 15MB 上限** | [upload_file_schema.py](../../api/internal/schema/upload_file_schema.py) 限制 | 分片上传 + 秒传 + 断点续传；上限按套餐分级 | ✅ 已完成（P2B：分片上传链路 + 秒传 + 断点续传；上限按 `PlanEntitlement.max_single_file_gb` 分级；单次接口上限放宽为 64MB 防御常量。**注**：未配置该权益时回退 15MB，需管理员在套餐板块配置） |
| 3 | **上传白名单无音视频** | [upload_file_entity.py](../../api/internal/entity/upload_file_entity.py) 仅图片 + 文档 | 增加 mp4/mov/avi/mkv/webm、mp3/wav/m4a/aac 等 | ✅ 已完成（P2A：实体层白名单 + `allowed_extensions_for_base_type()` + 存储层全类型并集 + `upload_document` 类型硬约束） |
| 4 | **多模态产物不入库** | 抽帧 / ASR / OCR 产物丢弃 | 接入索引链路，产物写 Segment + 向量化 | ✅ 已完成（P2A：`KnowledgeMediaExtractorService` 产物直达 Segment + 向量化；L2 产物属 P3） |
| 5 | **标签未接入知识库** | 无 `KnowledgeBaseTag` / `DocumentTag` | 新增关联表，复用 Tag 服务 | ✅ 已修复（模型层表 + FK + 唯一约束为 P1；服务层 `KnowledgeTagService` 与三条素材标签路由为 P3） |
| 6 | **无板块分类与分区** | 仅扁平 `KnowledgeBase` | 新增 `base_type` / `partition_mode` / `KnowledgePartition` | ✅ 已修复（含两级树服务层校验 + 用户端创建入口 + 分区增删查路由 + 对话内建库工具）|
| 7 | **存储配额空白** | account / Plan 均无存储字段 | 按 §2.6 新增配额模型 | ✅ 已修复（`PlanEntitlement.storage_quota_gb` + `StorageQuotaService`）|
| 8 | **用量无 account 维度** | `StorageConfigService.get_storage_stats()` 仅全局 | 新增按 account 聚合计量 | ✅ 已修复（`account_storage_usage` + `StorageQuotaService.get_usage_summary`）|
| 9 | **解析无分级策略** | 无档位概念 | 按 §3.3 实现 L1 / L2 双阶段 | ✅ 已修复（L1 为 P2A：多媒体走 L1 解析并写 `parse_profile.tier1`；L2 为 P3：`build_document_l2_task` + 触发路由 `/documents/<id>/l2` 按需触发并写 `parse_profile.tier2`，见 §9.2） |
| 10 | **无视频轻量编辑** | ffmpeg 仅用于抽帧 | 按 §5.2 新增裁剪 / 拼接 / 字幕 | ⬜ P4 |
| 11 | **配额并发超卖** | `check_quota`（读）与 `add_usage`（写）分离，无锁，两个会话可同时通过校验 | 新增 `StorageQuotaService.consume_quota()`，在 `FOR UPDATE` 行锁内完成校验+累加 | ✅ 已修复（分片 `complete` / 秒传 `instant` 改为合并前原子预占，失败释放预占）|
| 12 | **合并失败留孤儿文件** | `merge_chunks` 流式写目标对象，中途失败不清理半成品 | 在 `except` 中 `delete_object(target_key)` 回收 | ✅ 已修复（`LocalStorageService.merge_chunks`）|

> **迁移链注意**（`api/internal/migration/versions/p1a2b3c4d5e6_*.py`）：该迁移的 `down_revision` 必须指向**已提交**的迁移（现为 `n8c9d0e1f2a3`）。历史上曾误指向未纳入版本控制的 `o9d0e1f2a3b4`，导致全新 clone / CI 上 `alembic upgrade head` 因 "Revision ... is not present" 崩溃。`api/test/internal/migration/test_migration_graph_integrity.py` 以 git 跟踪的文件重建迁移图，对此类断链与多 head 设有守卫。

---

## 九、实施分期

### 9.1 能力依赖

```text
配额与计费 ─────┐
              ├──→ 上传链路改造 ──→ 多模态解析 ──→ 检索取料 ──→ 视频编辑 ──→ 前台运维
板块与分区 ─────┘   (分片/白名单/     (L1/L2 +      (含视觉向量)  (裁剪/拼接/字幕)  (双入口)
                    size升级)         产物入库)
```

### 9.2 阶段划分

| 阶段 | 目标 | 核心交付 | 可独立验证 | 状态 |
| --- | --- | --- | --- | --- |
| **P1 数据基座** | 模型与配额能跑 | `KnowledgeBase` 加 `base_type`/`partition_mode`；新增 `KnowledgePartition`、`KnowledgeBaseTag`/`DocumentTag`、`account_storage_usage`；`UploadFile.size` → `BigInteger`；`PlanEntitlement` 挂 `storage_quota_gb` + `storage_addon` plan_type；`StorageQuotaService` | 建板块、传小文件、配额正确累加与拒绝 | ✅ **已完成**（实施计划：[2026-09-12-knowledge-base-p1-foundation.md](../superpowers/plans/2026-09-12-knowledge-base-p1-foundation.md)） |
| **P2 上传与解析** | 大文件与多模态入库 | **P2A（已完成）**：白名单扩音视频 + 类型硬约束；`KnowledgeMediaExtractorService` 扩展多模态分支；L1 解析接入 `video_analyze`/`vision_analyze`/`audio_service` 产物写 Segment + 向量化。**P2B（已完成）**：分片上传 + 秒传 + 断点续传；单文件上限改为按套餐权益分级 | P2A：传视频/音频/图片 → 可被语义检索命中（✅ 已达成）；P2B：分片链路本身可传 GB 级（流式合并，不整文件入内存）——**⚠️ 前提是管理员已在套餐配置 `max_single_file_gb` 权益，否则仍按默认 15MB 拒绝** | ✅ **已完成**（P2A 计划：[2026-09-14-knowledge-base-p2a-multimodal-ingest.md](../superpowers/plans/2026-09-14-knowledge-base-p2a-multimodal-ingest.md)；P2B 计划：[2026-09-14-knowledge-base-p2b-chunked-upload.md](../superpowers/plans/2026-09-14-knowledge-base-p2b-chunked-upload.md)） |
| **P3 检索与视觉向量** | 取料能力完整 | 关键帧视觉向量独立索引；检索工具支持分区/标签/媒体类型/相似度阈值过滤；L2 按需解析触发 | 以图搜图命中画面相似素材；文本 query 跨模态召回画面；按分区与媒体类型过滤生效 | ✅ **已完成**（P3 实施计划：[2026-09-15-knowledge-base-p3-retrieval-and-visual-vectors.md](../superpowers/plans/2026-09-15-knowledge-base-p3-retrieval-and-visual-vectors.md)） |
| **P4 视频轻量编辑** | 「改细节」可落地 | `video_trim` / `video_concat` / `video_subtitle` 工具 + Celery 转码队列 + 对话框预览 | 对话里裁剪片段并预览成片 | ⬜ 未开始 |
| **P5 前台与运维** | 用户可管理 | 板块列表/详情/分区树导航/素材网格/素材详情/用量面板 + 扩容入口；小钰帮传（desktop bridge）打通；外部数据源同步纳入配额校验 | 双入口操作同一数据；小钰帮传成功 | ⬜ 未开始 |

**最小可用闭环 = P1 + P2 完成**（素材能入库、能被检索）。P2A 完成后，多模态素材的"入库 + 可检索"闭环已达成；P2B（大文件分片上传）落地后，P2 已完整收口。

> **P1 落地说明（与设计稿的差异）**：
> - `KnowledgePartition.visibility_scope` 按设计已落地（默认继承板块可见性），仅作**字段预留**，分区级权限校验首版不做。
> - `UploadFile.size` 已升级 `BigInteger`；`upload_file` 表另有 `storage_backend` 字段（运行时代理按此路由），非本设计新增但为配额与后端切换的既有基础。
> - 上传白名单的 `ALLOWED_VIDEO_EXTENSION` / `ALLOWED_AUDIO_EXTENSION` 已就绪；**分片上传与解除单文件 15MB 上限已在 P2B 落地**（见 9.2）。
> - 配额校验的落点由设计稿的 `StorageQuotaService.check(account_id, incoming_bytes)` 实现为 `check_quota`，并在 `RuntimeStorageProxy` 统一收口（覆盖用户上传 / Agent 产物 / 后续同步）。

> **P2A 落地说明（与设计稿的差异）**：
> - 多模态分支落在新增的 `KnowledgeMediaExtractorService`，而非设计稿所述的 `FileExtractor` 扩展（`FileExtractor` 保持文本抽取职责，多媒体走独立的 `_build_media_document` 直达路径）。
> - 视觉模型调用与视频抽帧抽取为共享模块 `internal/core/vision/vision_invoke.py`，内置工具与知识库解析共用。
> - 多媒体片段是"每次完整重新生成"的产物：重解析前清理该文档旧片段（含向量），保证幂等。
> - L1 解析状态写入 `parse_profile.tier1`（`status` / `media_type` / `segment_count`；P3 又补 `video_frame_count` 与 `frames`）；视频 L1 已补 ASR 音轨提取（`source: "audio_transcript"` 片段）与关键帧留存（`frame_url`）。（音轨 ASR 与帧留存为 P3 落地，见下方 P3 落地说明。）

> **P3 落地说明（与设计稿的差异）**：
> - **视觉向量不再"融合排序"**：设计稿原假设「视觉与文本是两个独立语义空间」，实测 `Qwen/Qwen3-VL-Embedding-8B` 把文本/图片/视频映射到**同一语义空间**，因此文本 query 可直接与库内图片向量比对余弦相似度，`search_by_text` / `search_by_image` 共用一套排序；视觉向量定位为并行的补充召回通道，由上层与文本召回合并。
> - **视觉编码服务不注册 langchain `model_class_registry`**：该模型 REST 入参（裸字符串 / `{"image":...}` / 对象数组）与 `OpenAIEmbeddings` 不兼容，注册会导致静默只编码文本，故 `VisualEmbeddingService` 走独立 HTTP 调用。
> - **L2 触发链路落在独立 Celery 任务 + 显式触发入口**：任务 `internal.task.knowledge_l2_tasks.build_document_l2_task`（`bind=True` / `max_retries=2` / `default_retry_delay=60`），**不加 beat 条目**（按需触发，不做定时轮询）；触发入口为 `POST /space/knowledge-bases/<kb_id>/documents/<document_id>/l2` → `KnowledgeBaseService.trigger_document_l2`（Celery 优先、失败回退同步）。状态写 `parse_profile.tier2`，失败只标 error 不回滚 L1 产物，增强时**回写同一批 Segment 不新建**。
> - **检索过滤全部 SQL 下推**：分区 / 媒体类型 / 素材id / 相似度阈值直接进向量 SQL（命中 HNSW 索引）；全文分支需先把分区/媒体类型解析为素材 id 再与标签取交集；**标签无命中 fail closed**，不退化为不过滤。
> - 帧留存**不计用户存储配额**（解析中间产物，随素材删除）。

### 9.3 明确不做

| 项 | 理由 | 结构预留 |
| --- | --- | --- |
| 分区级权限隔离 | 分区是组织手段非权限边界；引入需鉴权链路全栈改造；当前无团队协作需求 | ✅ `KnowledgePartition.visibility_scope` 字段预留 |
| 无限层级分区 | 两层覆盖多数需求；深树带来 UI 混乱与 Agent 导航复杂化 | ✅ `parent_id` 支持未来放开 |
| 视频转场 / 特效 / 多轨音画 | 属专业剪辑领域，与「自动做短视频」定位不符，会拖垮本期 | 由独立项目承载 |
| 跨用户素材共享 | 延续 §18.5 知识库私有原则 | — |
| 分区级独立索引 | 检索仍以板块为作用域边界 | — |

---

## 十、文档同步映射

按 [AGENTS.md](../../AGENTS.md)「架构文档同步（强制规则）」，本设计落地后须同步：

| 文档 | 更新内容 |
| --- | --- |
| [product-vision.md](./product-vision.md) | 落地状态表第 11 条（视频素材）更新状态；新增知识库板块 / 分区 / 配额条目 |
| [modules/02-knowledge-base.md](./modules/02-knowledge-base.md) | 新增板块类型、两级分区体系、多模态解析、容量配额章节 |
| [modules/06-file-storage.md](./modules/06-file-storage.md) | 新增分片上传、存储配额、按 account 计量 |
| [modules/07-public-ai-config.md](./modules/07-public-ai-config.md) | 新增 `storage_quota_gb` 权益与存储类 feature_key |
| [docs/rbac.md](../rbac.md) | 新增存储扩容相关权限 |
| [execution-roadmap.md](./execution-roadmap.md) | 新增本期五个阶段任务状态 |

---

## 十一、待确认事项

以下细节在实施前需进一步确认：

1. ~~**视觉编码模型选型**：CLIP / 中文 CLIP / 其他，及接入 `ModelPoolConfig` 的具体方式~~ → **已定稿并落地（P3）**：选定硅基流动 `Qwen/Qwen3-VL-Embedding-8B`，以新模型类型 `visual_embedding` 接入 `ModelPoolConfig`，维度固定 1536（MRL 降维）。模型类型登记已落地（`ModelType.VISUAL_EMBEDDING` + 后端/前端各两份白名单已同步，并有 `test_model_type_parity.py` 防漂移守卫）；编码服务 `VisualEmbeddingService`、向量表 `video_visual_embedding`（含 HNSW 余弦索引）与迁移 `c9d0e1f2a3b4` / `dae1f2a3b4c5` 均已落地。
2. **转码配额计量**：视频编辑的 CPU 转码是否单独计费，还是计入现有算力配额
3. **外部数据源同步的配额策略**：同步超限时是整体拒绝、还是截断同步、还是仅告警
4. **分级档位阈值**：短音频 5min 的切分阈值是否需按套餐/场景调整
5. ~~**大文件分片规格**：分片大小、并发数、断点续传的存储方案~~ → **已定稿（P2B）**：分片大小 5MB、前端并发 3、会话状态存 Redis（多 worker 共享，key 前缀 `chunked_upload:`）、会话 TTL 24h（秒传指纹 TTL 7 天）；分片暂存 `storage/chunks/{session_id}/`，完成时流式合并。详见 [modules/06-file-storage.md §17.13](./modules/06-file-storage.md#1713-分片上传p2b-已落地)
