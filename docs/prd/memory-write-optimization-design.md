# 记忆写入系统优化设计文档

> **文档信息**
>
> | 项 | 值 |
> |---|---|
> | 文档名称 | 显式记忆写入优化 — 语义检测 + 写时冲突 + 连锁优化 |
> | 版本 | v2.0 |
> | 日期 | 2026-07-14 |
> | 定位 | 记忆系统写入路径的精确化改造设计 |
> | 配套文档 | architecture-design.md（第 16 章脑启发记忆系统）<br>memory-system/01-data-models-and-write-path.md（数据模型与写入路径）<br>memory-system/02-storage-and-retrieval.md（存储层与读取路径）<br>memory-system/03-consolidation-skill-policy-api.md（巩固引擎、技能池、Policy 层与 API） |

---

## 1. 背景与问题定义

### 1.1 当前系统的问题

当前记忆写入系统依赖 `SalienceScorer` 的 5 因子加权评分：

| 因子 | 权重 | 来源 | 说明 |
|---|---|---|---|
| emotion_intensity | 0.25 | LLM | 情绪强度 |
| novelty | 0.20 | LLM | 新颖性 |
| goal_relevance | 0.25 | LLM | 目标相关性 |
| outcome_impact | 0.20 | LLM | 结果影响力 |
| rehearsal_boost | 0.10 | Redis | 复述强化（重复计数） |

**核心缺陷**：用户说"我喜欢吃苹果"时，情绪=0.3、新颖=0.2、目标=0.3、影响=0.2、复述=0.0 → 总分≈0.25 → 仅走 STATS 路径（仅更新计数器，不写向量），**偏好根本未被真正记住**。必须重复说 3 次，rehearsal_boost 才能拉高分数。

### 1.2 目标

- 用户说"我喜欢吃苹果"，**立即写入**，不等重复
- 用户从"喜欢菠萝"变"讨厌菠萝"，**即时 supersede**，不等批量 consolidation
- 用户既喜欢苹果又喜欢菠萝，**共存不冲突**
- 不破坏现有 5 因子评分系统，作为增量层插入
- 复用现有四时间戳双时间模型、实体消解、LedgerWriter 三路径规范

---

## 2. 整体架构

### 2.1 三层决策架构

在 `MemoryWriteService.write_from_event()` 中插入前置检测层，形成三层决策：

```text
MemoryEvent
  │
  ▼
① ExplicitStatementDetector（新增）
  │  正则预筛 → LLM 确认
  │
  ├─ 命中且高置信度（≥0.85）→ ② 写时冲突检测 → 直接调用 LedgerWriter.write_full_path()（跳过 SalienceScorer）
  │                                    ↓
  │                               发现同 subject 旧记忆？
  │                              ├─ 同极性 → COMPLEMENT（共存）
  │                              ├─ 反极性 → SUPERSEDE 旧记忆（复用四时间戳模型）
  │                              └─ 无匹配 → 直接写入
  │
  ├─ 命中但低置信度（0.5~0.85）→ 走 SalienceScorer 6 因子评分，explicitness=0.8 加权拉高
  │
  └─ 未命中 → 走 SalienceScorer 6 因子评分，explicitness=0.0
```

### 2.2 核心调用链

```python
class MemoryWriteService:
    async def write_from_event(self, event: MemoryEvent):
        # ── 第 1 层：显式陈述检测 ──
        explicit_result = await self._explicit_detector.detect(event)

        if explicit_result and explicit_result.confidence >= self._config.fast_path_threshold:
            # ── 快路径：直接 FULL 写入，绕过 SalienceScorer ──
            await self._write_time_conflict_resolver.resolve_and_write(
                event, explicit_result, write_path=WritePath.FULL
            )
            # 内部调用 LedgerWriter.write_full_path(event, explicit_result)
            return

        # ── 第 2 层：SalienceScorer 6 因子评分（传入 explicit_result）──
        salience = await self._salience_scorer.score(event, explicit_result)

        # ── 第 3 层：按路由写入 ──
        if salience.write_path == WritePath.FULL:
            await self._write_time_conflict_resolver.resolve_and_write(
                event, explicit_result, write_path=WritePath.FULL
            )
        elif salience.write_path == WritePath.SUMMARY:
            await self._ledger_writer.write_summary_path(event, salience)
        else:  # STATS
            await self._ledger_writer.write_stats_path(event, salience)
```

**关键点**：
- 快路径（confidence ≥ 0.85）：绕过 SalienceScorer，直接 `LedgerWriter.write_full_path()` + 写时冲突检测
- 拉高路径（0.5 ≤ confidence < 0.85）：走 SalienceScorer 6 因子评分，按路由写入
- 未命中路径：走 SalienceScorer 6 因子评分（explicitness=0.0），按路由写入
- 写时冲突检测只在 FULL 路径触发（SUMMARY/STATS 不需要，因为不会创建新的偏好记忆）

### 2.3 核心原则

| 原则 | 说明 |
|---|---|
| 立即兑现 | 显式自我陈述立即写入，不等重复 |
| 即时冲突 | 偏好变化即时 supersede，不等批量 consolidation |
| 共存优先 | 不同 subject 的偏好共存，不误判为冲突 |
| 增量插入 | 不破坏现有 5 因子评分，作为前置层插入 |
| 复用现有模型 | SUPERSEDE 复用四时间戳模型，写入复用 LedgerWriter 三路径规范 |

---

## 3. ExplicitStatementDetector 详细设计

### 3.1 正则预筛模式库

基于中文 NLP 语料，覆盖 7 大类别：

```python
EXPLICIT_PATTERNS = {
    # ① 偏好类 — 正向喜好
    "preference": [
        r"我(?:很|最|特别|比较)?(?:喜欢|偏爱|钟爱|酷爱|偏好|首选|倾向于)",
        r"我(?:更)?喜欢",
        r"我对.+(?:感兴趣|有偏好)",
    ],
    # ② 习惯类 — 行为模式
    "habit": [
        r"我(?:习惯|习惯于|总是|通常|经常|一般|每次|一贯|一向|历来)",
        r"我(?:习惯|总是)用",
        r"我(?:做事|写代码|开发).+(?:习惯|风格|方式)",
    ],
    # ③ 身份事实类 — 个人属性
    "identity": [
        r"我(?:是|叫|在做).{2,20}(?:工作|职业|岗位|工程师|开发者|设计师)",
        r"我(?:在|住|来自|毕业于)",
        r"我(?:今年|现在).{0,5}(?:岁|年级)",
    ],
    # ④ 厌恶/否定类 — 反向偏好
    "aversion": [
        r"我(?:很|特别|比较)?(?:讨厌|不喜欢|反感|厌恶|憎恨|受不了|抵触)",
        r"(?:别|不要|不用|千万别)给(?:我|我推)",
        r"我(?:对|对.+).+(?:过敏|不适应|不接受)",
    ],
    # ⑤ 目标/计划类
    "goal": [
        r"我(?:想|打算|计划|准备|希望|目标是要)",
        r"我(?:正在|在)学",
    ],
    # ⑥ 元指令类 — 显式记忆命令
    "meta_instruction": [
        r"(?:记住|帮我记住|以后都|请总是|别忘了|记一下)",
        r"(?:别再|以后不要|不要再)",
    ],
    # ⑦ 能力类
    "capability": [
        r"我(?:会|能|擅长|精通|熟练)",
        r"我(?:不会|不擅长|无法|搞不定)",
    ],
}
```

### 3.2 检测流程

```text
用户消息
  │
  ▼
正则扫描（遍历 7 类模式，零 LLM 调用）
  │
  ├─ 无命中 → 返回 None，走原 5 因子评分
  │
  └─ 有命中 → 提取命中类别 + 命中片段
              │
              ▼
         LLM 确认（轻量结构化输出，带降级）
         输入: 命中片段 + 上下文
         输出: {
           is_explicit: bool,
           category: str,
           subject: str,           # 陈述主体（如"苹果""菠萝""Vim"）
           polarity: "positive" | "negative" | "neutral",
           confidence: 0.0-1.0,
           summary: str,           # 结构化摘要
           temporal_marker: bool   # 是否含时态标记（"了""现在""已经"）
         }
              │
              ├─ confidence ≥ 0.85 → 快路径（直接 LedgerWriter.write_full_path()）
              ├─ 0.5 ≤ confidence < 0.85 → explicitness=0.8，走 6 因子评分拉高
              └─ confidence < 0.5 → 忽略，走原评分（explicitness=0.0）
```

### 3.3 LLM 确认 Prompt

```text
你是一个用户陈述识别专家。请分析以下用户消息是否包含明确的自我陈述。

用户消息: {message}
命中模式类别: {category}
命中片段: {matched_text}

请判断:
1. 这是用户在明确表达自己的偏好/习惯/身份/厌恶/目标/能力，还是只是随口提及？
2. 提取陈述的主体（如"苹果""Python""晚睡"）
3. 判断极性：正向（喜欢/会/习惯）、负向（讨厌/不会/不习惯）、中性（身份事实）
4. 是否包含时态变化标记（"了""现在""已经""不...了"）—— 这表示偏好可能发生了变化

返回 JSON: {is_explicit, category, subject, polarity, confidence, summary, temporal_marker}
```

### 3.4 输出数据结构

```python
@dataclass
class ExplicitDetectionResult:
    is_explicit: bool
    category: str              # preference/habit/identity/aversion/goal/meta_instruction/capability
    subject: str               # 陈述主体
    polarity: str              # positive/negative/neutral
    confidence: float          # 0.0-1.0
    summary: str               # 结构化摘要
    temporal_marker: bool      # 是否含时态标记
    matched_pattern: str       # 命中的正则模式（调试用）
    fallback: bool = False     # 是否为降级模式（LLM 不可用时的纯正则结果）
```

### 3.5 降级策略

当 LLM 不可用时，ExplicitStatementDetector 降级到纯正则模式：

| 依赖状态 | ExplicitStatementDetector 行为 | 写入路径 |
|---|---|---|
| LLM 正常 | 正则预筛 + LLM 确认 | 快路径 / 拉高 / 原评分 |
| LLM 超时/不可用 | 仅正则预筛（降级模式） | 命中正则 → 走 6 因子评分（explicitness=0.5） |
| LLM + 正则均不可用 | 跳过显式检测 | 走原 5 因子评分 |
| Neo4j 挂 | 显式检测正常，但写时冲突检测跳过 | 直接写入，等批量 consolidation 兜底 |
| pgvector 挂 | 显式检测正常，向量兜底跳过 | 仅用 Cypher 精确匹配 |
| Redis 挂 | 显式检测正常（rehearsal_boost=0） | 走原评分，F 因子降级为 0.5 |

```python
class ExplicitStatementDetector:
    async def detect(self, event: MemoryEvent) -> Optional[ExplicitDetectionResult]:
        # 1. 正则预筛（始终执行）
        regex_hits = self._regex_scan(event.content)
        if not regex_hits:
            return None

        # 2. LLM 确认（带降级）
        if not self._config.llm_fallback_enabled:
            return None  # 降级关闭，走原评分

        try:
            result = await asyncio.wait_for(
                self._llm_confirm(event, regex_hits),
                timeout=self._config.llm_timeout_seconds
            )
            return result
        except (asyncio.TimeoutError, Exception) as e:
            logger.warning("LLM confirm failed, fallback to regex-only: %s", e)
            # 降级：仅正则命中，confidence 设为 0.6（拉高路径）
            return ExplicitDetectionResult(
                is_explicit=True,
                category=regex_hits[0].category,
                subject=regex_hits[0].matched_text,  # 未经 LLM 提取，用原始片段
                polarity="neutral",  # 未经 LLM 判断，保守中性
                confidence=0.6,  # 拉高路径阈值
                summary=regex_hits[0].matched_text,
                temporal_marker=False,
                matched_pattern=regex_hits[0].pattern,
                fallback=True  # 标记降级模式
            )
```

---

## 4. 写时冲突检测详细设计

### 4.1 结构化元数据存储

显式陈述写入时，在 `user_memory.metadata_` JSONB 和 Neo4j 节点属性中同步存储结构化字段：

**pgvector（user_memory.metadata_）**：
```json
{
  "detection": {
    "category": "preference",
    "subject": "菠萝",
    "polarity": "positive",
    "confidence": 0.95,
    "summary": "用户喜欢吃菠萝",
    "source": "explicit_detector",
    "temporal_marker": false
  }
}
```

**Neo4j 节点属性**（写入 Episode 节点）：
```cypher
e.explicit_category = "preference"
e.explicit_subject = "菠萝"
e.explicit_polarity = "positive"
```

### 4.2 写时冲突检测流程（复用四时间戳模型）

```text
新显式陈述写入前
  │  subject="菠萝" polarity="negative" category="preference"
  │
  ▼
① 精确匹配查询（Cypher + SQL 双查）
  Cypher: MATCH (e:MemoryNode {user_id: $uid, type: 'episode',
                    explicit_category: 'preference',
                    explicit_subject: '菠萝', is_active: true})
          WHERE e.t_invalidated_at IS NULL
          RETURN e
  │
  ├─ 无匹配 → ② 向量兜底（仅 preference/aversion 类）
  │   用新陈述 embedding 查询同 category 现有记忆
  │   cosine 相似度 > 0.85 → 视为同 subject → 走极性比较
  │
  │   向量兜底也无匹配 → 直接写入新记忆
  │
  └─ 有匹配 → ③ 极性比较
       │
       ├─ 同极性（positive + positive）
       │   → 已存在相同偏好，跳过写入（仅更新 last_accessed_at）
       │
       ├─ 反极性（positive + negative 或 negative + positive）
       │   → SUPERSEDE：复用四时间戳模型标记旧记忆失效 + 写入新记忆
       │   → 旧记忆 t_invalidated_at=now, invalidated_by=新记忆id
       │   → 创建 SUPERSEDED_BY 边
       │
       └─ 中性（identity 类，如"我是工程师"）
           → 相同 subject → UPDATE：更新现有记忆内容
```

### 4.3 SUPERSEDE 操作（复用四时间戳双时间模型）

复用现有 MemoryEdge 四时间戳模型（t_valid_at / t_invalidated_at / t_transaction_start / t_transaction_end / invalidated_by），而非自创字段：

```cypher
// 旧 Episode 节点标记失效（复用四时间戳模型）
MATCH (old:MemoryNode {id: $old_id})
SET old.t_invalidated_at = datetime(),
    old.invalidated_by = $new_id,
    old.is_active = false

// 创建 SUPERSEDED_BY 边（复用现有 ConflictDetector 的边类型）
CREATE (old)-[:SUPERSEDED_BY {
  t_valid_at: datetime(),
  t_transaction_start: datetime()
}]->(new:MemoryNode {id: $new_id})
```

pgvector 侧同步：
```sql
UPDATE user_memory
SET t_invalidated_at = NOW(),
    invalidated_by = $new_id,
    embedding = NULL  -- 从向量索引移除
WHERE id = $old_id
```

**关键差异**：
| 维度 | 自创方案（已废弃） | 复用四时间戳模型（采用） |
|---|---|---|
| 失效标记 | `status='superseded'`（自创字段） | `t_invalidated_at=now`（复用现有字段） |
| 失效指向 | `superseded_by` 元数据 | `invalidated_by` 字段（复用现有字段） |
| 边类型 | `SUPERSEDED_BY`（正确，复用） | `SUPERSEDED_BY`（不变） |
| 检索过滤 | `WHERE status='active'` | `WHERE t_invalidated_at IS NULL` |

### 4.4 时态标记处理

当 LLM 确认检测到 `temporal_marker=true`（如"了""现在""已经"），自动触发 SUPERSEDE 检查：

| 用户说 | subject | polarity | temporal_marker | 系统行为 |
|---|---|---|---|---|
| "我喜欢菠萝" | 菠萝 | positive | false | 新写入 |
| "我讨厌菠萝了" | 菠萝 | negative | true | SUPERSEDE 旧 positive |
| "我现在不喜欢苹果了" | 苹果 | negative | true | SUPERSEDE 旧 positive |
| "我已经改用 VSCode 了" | VSCode | positive | true | SUPERSEDE 旧 editor 偏好 |

### 4.5 用户示例完整流转

| 时间 | 用户说 | 系统行为 | 记忆库状态 |
|---|---|---|---|
| T1 | "我喜欢吃苹果" | 快路径写入，subject=苹果, polarity=positive | `[active] 喜欢苹果(+)` |
| T2 | "我喜欢吃菠萝" | 快路径写入，subject=菠萝, polarity=positive | `[active] 喜欢苹果(+)`, `[active] 喜欢菠萝(+)` |
| T3 | "我讨厌吃菠萝了" | 查到菠萝(+) → 反极性 + temporal_marker → SUPERSEDE | `[active] 喜欢苹果(+)`, `[t_invalidated_at=now] 喜欢菠萝(+)`, `[active] 讨厌菠萝(-)` |
| T4 | 检索"用户对菠萝的偏好" | 只返回 t_invalidated_at IS NULL 的记忆 | 返回"讨厌菠萝(-)" |

### 4.6 与现有 ConflictDetector 的关系

| 维度 | 现有 ConflictDetector（批量） | 新增写时冲突检测（实时） |
|---|---|---|
| **触发时机** | 批量 consolidation（异步周期任务） | 写入时即时 |
| **检测范围** | 全部热记忆两两比对 | 仅同 category + 同 subject |
| **检测方式** | LLM 判断每对关系 | 结构化极性比较（零 LLM） |
| **适用场景** | 发现历史遗留冲突 | 处理实时偏好变化 |
| **关系** | **互补**，写时检测处理增量，批量检测兜底处理遗漏 | |

批量 ConflictDetector 优化：跳过已有 `SUPERSEDED_BY` 边的对 + 跳过同 subject 已处理的。

---

## 5. 全系统影响分析

### 5.1 Neo4j 图存储影响

**问题**：结构化字段只存在 pgvector metadata 会导致图查询盲区。

**优化**：写入时同步到 Neo4j Episode 节点属性（`explicit_category`、`explicit_subject`、`explicit_polarity`），使写时冲突检测可直接用 Cypher 查询。

### 5.2 冲突死角

| 死角 | 场景 | 严重程度 | 处理建议 |
|---|---|---|---|
| **跨类别冲突** | "我喜欢加班"(preference+) + "我是自由职业者"(identity) | 中 | 暂不处理，留给批量 ConflictDetector 兜底 |
| **时态标记** | "我不怎么喜欢苹果**了**" — "了"表示状态变化 | 高 | LLM 确认时检测时态词，自动触发 SUPERSEDE |
| **习惯 vs 目标** | "我习惯晚睡"(habit) + "我想改掉晚睡"(goal) | 中 | 暂不处理，检索时可通过 polarity 过滤 |
| **双写一致性** | SUPERSEDE 时需同时更新 Neo4j + pgvector | 高 | MemoryWriteService 中事务化，批量 consolidation 兜底修复 |

### 5.3 连锁优化机会

| 优化点 | 当前状态 | 优化后 | 收益 |
|---|---|---|---|
| **实体抽取复用** | EntityExtractor 对每条消息调 LLM | 显式检测已提取 subject，作为实体种子传入 | 省 1 次 LLM 调用/显式消息 |
| **显著性评分跳过** | 每条消息调 4 次 LLM 因子 | 快路径跳过全部 4 次 LLM | 省 4 次 LLM 调用/显式消息 |
| **批量冲突检测减负** | ConflictDetector 两两比对所有热记忆 | 跳过已有 SUPERSEDED_BY 边的对 | 批量任务耗时降低 |
| **检索过滤增强** | 检索返回所有 active 记忆 | 按 polarity 过滤，优先返回最新偏好 | 检索精度提升 |
| **衰减豁免** | HebbianDecay 对所有记忆统一衰减 | 显式偏好/身份类记忆 lambda_decay ×0.1 | 稳定用户画像不被遗忘 |
| **Digest 分组渲染** | DigestManager 按时间排列 | 按 category + polarity 分组展示 | 摘要可读性提升 |

### 5.4 SalienceScorer 6 因子集成

#### 5.4.1 新的加权求和公式

```python
class SalienceScorer:
    async def score(self, event: MemoryEvent,
                    explicit_result: Optional[ExplicitDetectionResult] = None) -> SalienceResult:
        # 并行计算原 4 个独立因子（asyncio.gather）
        E, S, G, O = await asyncio.gather(...)  # emotion, novelty, goal, outcome
        F = await self._get_rehearsal_boost(event)  # 从 Redis 读取 access_count

        # 第 6 因子：explicitness（由前置 ExplicitStatementDetector 传入）
        if explicit_result and explicit_result.is_explicit:
            if explicit_result.confidence >= self._config.fast_path_threshold:
                # 快路径：不应走到这里，快路径在外层已直接调用 LedgerWriter
                explicitness = 1.0
            else:
                # 因子拉高路径：confidence 在 [0.5, 0.85) 时
                explicitness = 0.8
        else:
            explicitness = 0.0

        # 新的加权求和（6 因子）
        total = (w1*E + w2*S + w3*G + w4*O + w5*F + w6*explicitness)

        return SalienceResult(
            emotion_intensity=E, novelty=S, goal_relevance=G,
            outcome_impact=O, rehearsal_boost=F,
            explicitness=explicitness,  # 新增字段
            total_score=total,
            write_path=self.route(total)
        )
```

#### 5.4.2 explicitness 因子取值规则

| 检测结果 | explicitness 取值 | 路由 |
|---|---|---|
| 未命中正则 | 0.0 | 走原 5 因子评分 |
| 命中但 confidence < 0.5 | 0.0 | 走原 5 因子评分 |
| 命中且 0.5 ≤ confidence < 0.85 | 0.8 | 走 6 因子评分（拉高） |
| 命中且 confidence ≥ 0.85 | （快路径，不进入评分） | 直接 LedgerWriter.write_full_path() |

#### 5.4.3 权重重分配

```python
# 原权重
weights = {"emotion": 0.25, "novelty": 0.20, "goal_relevance": 0.25,
           "outcome_impact": 0.20, "rehearsal": 0.10}

# 新权重（explicitness 从各因子等比分摊）
weights = {"emotion": 0.20, "novelty": 0.16, "goal_relevance": 0.20,
           "outcome_impact": 0.16, "rehearsal": 0.08, "explicitness": 0.20}
```

#### 5.4.4 阈值路由有效性验证

权重重分配后，验证阈值路由（>0.7/0.3-0.7/≤0.3）仍有效：

**场景 A**：非显式消息（explicitness=0.0）
- 最优情况：E=0.9, S=0.8, G=0.9, O=0.8, F=0.5
- total = 0.20×0.9 + 0.16×0.8 + 0.20×0.9 + 0.16×0.8 + 0.08×0.5 + 0.20×0.0 = 0.692
- 路由：SUMMARY（0.3 < 0.692 < 0.7）✓

**场景 B**：显式拉高消息（explicitness=0.8）
- 即使其他因子较低：E=0.3, S=0.2, G=0.3, O=0.2, F=0.0
- total = 0.20×0.3 + 0.16×0.2 + 0.20×0.3 + 0.16×0.2 + 0.08×0.0 + 0.20×0.8 = 0.412
- 路由：SUMMARY（0.3 < 0.412 < 0.7）✓ — 至少进入 SUMMARY 路径，记忆被写入

**场景 C**：显式拉高 + 其他因子也高
- E=0.7, S=0.6, G=0.7, O=0.6, F=0.3, explicitness=0.8
- total = 0.20×0.7 + 0.16×0.6 + 0.20×0.7 + 0.16×0.6 + 0.08×0.3 + 0.20×0.8 = 0.716
- 路由：FULL（> 0.7）✓

**结论**：阈值路由（>0.7/0.3-0.7/≤0.3）仍有效，explicitness=0.8 确保显式陈述至少进入 SUMMARY 路径。

### 5.5 实体消解集成

显式 subject 作为实体消解的种子，避免重复创建相同实体：

```python
class LedgerWriter:
    async def write_full_path(self, event: MemoryEvent,
                              explicit_result: Optional[ExplicitDetectionResult] = None):
        # 1. 创建 Episode 节点（记录这次显式陈述事件）
        episode = await self._create_episode_node(event, explicit_result)

        # 2. 实体抽取 + 消解
        if explicit_result and explicit_result.subject:
            # 显式检测已提取 subject，作为实体种子
            entities = await self._extract_entities_with_seed(
                event.content, seed_subject=explicit_result.subject
            )
        else:
            # 常规实体抽取
            entities = await self._entity_extractor.extract(event.content)

        # 3. 实体消解（三信号融合：向量 + BM25 + LLM）
        for entity in entities:
            resolved = await self._entity_resolver.resolve(entity, event.user_id)
            # resolved.existing_id != None → MERGE 到现有节点
            # resolved.existing_id == None → CREATE 新节点

        # 4. 创建 Episode → Entity 关系边
        await self._create_relations(episode, entities)

        # 5. pgvector 写入 Episode 内容向量
        await self._write_pgvector(episode, event.content)
```

**关键点**：
- 显式 subject 作为实体种子，优先参与消解（避免"菠萝"被多次创建）
- 消解流程不变（三信号融合），只是输入更精确
- 如果"菠萝"实体已存在，MERGE 到现有节点，只创建新的 Episode→Entity 边

### 5.6 HebbianDecay 豁免设计

复用现有 HebbianDecay 权重计算公式，在 `lambda_decay`（时间衰减系数）上引入类别系数：

```python
class HebbianDecay:
    def compute_weight(self, edge: MemoryEdge, now=None) -> float:
        if now is None:
            now = datetime.now(timezone.utc)
        cfg = self._config

        # ---- 1. 时间衰减（引入豁免系数）----
        days_elapsed = max(0.0, (now - edge.last_accessed_at).total_seconds() / 86400.0)

        # 豁免系数：根据显式类别调整时间衰减速率
        exemption_factor = 1.0  # 默认无豁免
        explicit_category = getattr(edge, 'explicit_category', None)
        if explicit_category in ('preference', 'identity', 'aversion'):
            exemption_factor = cfg.decay_exemption_strong   # 0.1
        elif explicit_category in ('habit', 'goal', 'capability'):
            exemption_factor = cfg.decay_exemption_medium   # 0.5

        # 调整后的时间衰减
        effective_lambda = cfg.lambda_decay * exemption_factor
        time_factor = math.exp(-effective_lambda * days_elapsed)

        # ---- 2. 共现增强（不变）----
        cooccurrence_factor = 1.0 + cfg.alpha_cooccurrence * edge.cooccurrence_count

        # ---- 3. 干扰惩罚（不变）----
        competitor_count = getattr(edge, 'competitor_count', 0)
        interference_factor = 1.0 / (1.0 + cfg.beta_interference * competitor_count)

        # ---- 综合计算（不变）----
        raw = edge.weight * time_factor * cooccurrence_factor * interference_factor
        normalized = 1.0 / (1.0 + math.exp(-5.0 * (raw - 0.5)))
        return max(0.0, min(1.0, normalized))
```

**关键点**：
- 豁免只影响 `time_factor`（时间衰减），不影响 `cooccurrence_factor` 和 `interference_factor`
- preference/identity/aversion 类：`lambda_decay × 0.1`（衰减速率降为 1/10）
- habit/goal/capability 类：`lambda_decay × 0.5`（衰减速率减半）
- 非显式记忆：`exemption_factor = 1.0`（无变化）
- 需要在 MemoryEdge 模型中增加 `explicit_category` 字段（或从节点属性读取）

### 5.7 SkillEmergence 种子提示

显式 capability 类陈述**不直接创建 Skill**，作为 SkillEmergence 的"种子提示"加速成熟，但技能仍需行为验证：

| 维度 | SkillEmergence（现有） | 显式 capability（新增） |
|---|---|---|
| 检测方式 | 从 Episode 频次挖掘（≥3 次） | LLM 确认用户自述能力 |
| 直接创建 Skill | 是（频次达标后） | **否**（仅作为种子提示） |
| 作用 | 通过行为模式验证技能 | 降低该技能的频次阈值，加速成熟 |

```python
class MemoryWriteService:
    async def write_from_event(self, event: MemoryEvent):
        explicit_result = await self._explicit_detector.detect(event)

        if explicit_result and explicit_result.category == 'capability':
            # 显式能力陈述 → 写入 Episode 记忆（保留原始陈述）
            # + 为 SkillEmergence 注册"种子提示"（不创建 Skill）
            await self._skill_emergence.register_seed_hint(
                user_id=event.user_id,
                skill_name=explicit_result.subject,
                polarity=explicit_result.polarity,
                source='explicit_statement'
            )
            # Episode 正常写入，不特殊处理
```

```python
class SkillEmergence:
    async def register_seed_hint(self, user_id, skill_name, polarity, source):
        """注册显式能力陈述作为种子提示，不创建 Skill 节点"""
        # 仅记录提示，降低后续频次阈值
        # polarity=positive → 该技能的 min_pattern_frequency 从 3 降为 1
        # polarity=negative → 该技能加入"避免推荐"列表
        await self._seed_hint_store.set(
            key=f"seed:{user_id}:{skill_name}",
            value={"polarity": polarity, "source": source, "created_at": now},
            ttl=90 * 86400  # 90 天有效
        )

    async def _check_skill_emergence(self, user_id, episode):
        """正常的技能涌现检测，但检查是否有种子提示"""
        seed_hints = await self._seed_hint_store.get_all(f"seed:{user_id}:*")

        for entity in episode.entities:
            seed = seed_hints.get(entity.name)
            if seed and seed['polarity'] == 'positive':
                min_freq = 1  # 有种子提示 → 降低频次阈值
            else:
                min_freq = self._config.min_pattern_frequency  # 3

            pattern_count = await self._count_patterns(user_id, entity.name)
            if pattern_count >= min_freq:
                await self._create_or_promote_skill(user_id, entity.name)
```

**流转示例**：

| 时间 | 用户行为 | 系统行为 | Skill 状态 |
|---|---|---|---|
| T1 | "我精通 Python" | 写入 Episode + 注册种子提示（min_freq=1） | 无 Skill |
| T2 | 用户实际使用 Python 完成任务 | SkillEmergence 检测到 1 次模式（阈值已降为 1） | CANDIDATE（种子加速） |
| T3 | 用户再次使用 Python | 频次=2 | EMERGING |
| T4 | 用户持续使用 Python | 频次≥3 + 成熟度达标 | ACTIVE |

### 5.8 DigestManager 分组渲染

显式偏好注入 DigestManager 的 UserProfile 部分，按 category + polarity 分组渲染（无 token 预算限制，用户体验优先）：

```python
class DigestManager:
    async def build_digest(self, user_id: str) -> MemoryDigest:
        # 查询所有 active 的显式偏好记忆（不限制数量）
        explicit_memories = await self._query_explicit_memories(user_id)

        # 按 category + polarity 分组
        profile = self._build_user_profile(explicit_memories)

        return MemoryDigest(
            user_profile=profile,
            top_skills=await self._get_top_skills(user_id),
            recent_events=await self._get_recent_events(user_id),
            active_tasks=await self._get_active_tasks(user_id)
        )

    def _build_user_profile(self, explicit_memories: list) -> str:
        """按 category + polarity 分组渲染用户画像，不限制条数"""
        groups = {
            "偏好": [],      # preference + positive
            "厌恶": [],      # aversion / preference + negative
            "习惯": [],      # habit
            "身份": [],      # identity
            "目标": [],      # goal
            "能力": [],      # capability
        }

        for mem in explicit_memories:
            category = mem.get('explicit_category')
            polarity = mem.get('explicit_polarity')
            summary = mem.get('content', '')

            if category == 'preference' and polarity == 'positive':
                groups["偏好"].append(summary)
            elif category == 'preference' and polarity == 'negative':
                groups["厌恶"].append(summary)
            elif category == 'aversion':
                groups["厌恶"].append(summary)
            elif category in groups:
                groups[category].append(summary)

        lines = []
        for group_name, items in groups.items():
            if items:
                lines.append(f"【{group_name}】{'、'.join(items)}")
        return '\n'.join(lines)
```

Cypher 查询（无 LIMIT）：
```cypher
MATCH (e:MemoryNode {user_id: $uid, type: 'episode', is_active: true})
WHERE e.t_invalidated_at IS NULL
  AND e.explicit_category IS NOT NULL
RETURN e.explicit_category AS category,
       e.explicit_polarity AS polarity,
       e.content AS content
ORDER BY e.created_at DESC
```

渲染示例：
```
【偏好】喜欢吃苹果、喜欢用 Vim、喜欢深色主题
【厌恶】讨厌菠萝、对花生过敏、不喜欢加班
【习惯】习惯晚睡、习惯用 Python 写脚本、习惯先写测试
【身份】是后端工程师、来自北京
【目标】想学 Rust、打算考架构师
【能力】精通 Python、熟练 Docker、会 K8s
```

### 5.9 图可视化中 superseded 记忆的展示

superseded 记忆在图可视化中的展示（**用户视角**，管理员不处理用户记忆内容）：

```text
用户图可视化展示规则：
┌─────────────────────────────────────────────────────────┐
│ superseded 记忆展示（用户查看自己的记忆图）            │
├─────────────────────────────────────────────────────────┤
│ • 节点颜色：灰色（区别于 active 的蓝色）                │
│ • 节点透明度：50%（视觉弱化）                           │
│ • 边类型：SUPERSEDED_BY 边用虚线 + 箭头指向新记忆       │
│ • 悬浮提示：显示 t_invalidated_at（失效时间）           │
│ • 默认隐藏：图可视化默认只显示 active 记忆              │
│   用户可勾选"显示历史记忆"查看变化轨迹                  │
└─────────────────────────────────────────────────────────┘
```

**用户可执行操作**（沿用现有图可视化规范）：
- 软删除（active 记忆）
- 彻底删除（active 记忆）
- 降低权重
- 编辑

**superseded 记忆用户不可操作**（只读历史记录），如确需修正由 consolidation 自动处理。

**管理员职责不变**：仅负责系统监控和配置调优，不处理用户记忆内容。

### 5.10 双写一致性保障

SUPERSEDE 操作采用"最终一致"策略（Neo4j 和 PostgreSQL 跨数据源无法做分布式事务）：

```text
MemoryWriteService._supersede_memory():
  1. Neo4j: 旧节点 t_invalidated_at=now, invalidated_by=新id, is_active=false
  2. Neo4j: 创建 SUPERSEDED_BY 边
  3. pgvector: user_memory SET t_invalidated_at=NOW(), invalidated_by=新id WHERE id=旧记忆id
  4. pgvector: 旧记忆 embedding = NULL（从向量索引中移除）
  5. 写入新记忆到 Neo4j + pgvector

  任一步骤失败 → 记 warning 日志，标记需要修复
  → 下次批量 consolidation 会发现并修复不一致
```

### 5.11 模块改动清单

| 模块 | 改动类型 | 内容 |
|---|---|---|
| `memory_write_service.py` | **核心修改** | 插入 ExplicitStatementDetector 前置层 + 写时冲突检测 + 三层决策调用链 |
| `ledger_writer.py` | **扩展** | 写入时携带 explicit_* 属性到 Neo4j Episode 节点 + 实体消解种子集成 |
| `memory_vector_service.py` | **扩展** | index_memory 时写入 detection metadata |
| `salience_scorer.py` | **扩展** | 新增 explicitness 因子（第 6 因子）+ 6 因子加权求和公式 |
| `hebbian_decay.py` | **扩展** | 显式记忆 lambda_decay 豁免系数 |
| `conflict_detector.py` | **优化** | 跳过已有 SUPERSEDED_BY 边的对 |
| `retriever.py` | **优化** | 检索时优先返回 t_invalidated_at IS NULL 的最新偏好 |
| `digest_manager.py` | **扩展** | 按 category + polarity 分组渲染用户画像 |
| `skill_emergence.py` | **扩展** | register_seed_hint 种子提示（不直接创建 Skill） |
| `memory_settings.py` | **扩展** | 新增 ExplicitDetectionConfig 配置（含降级配置） |
| **新增** `explicit_detector.py` | **新文件** | ExplicitStatementDetector |
| **新增** `write_time_conflict_resolver.py` | **新文件** | 写时冲突检测器（复用四时间戳模型） |

---

## 6. 配置扩展

```python
class ExplicitDetectionConfig(BaseModel):
    """显式陈述检测配置。"""

    # 总开关
    enabled: bool = True
    # 快路径置信度阈值（≥此值直接 FULL 写入，跳过 SalienceScorer）
    fast_path_threshold: float = 0.85
    # 因子拉高阈值（≥此值走 6 因子评分但 explicitness=0.8）
    boost_threshold: float = 0.5
    # explicitness 因子权重（从原 5 因子权重中分摊）
    explicitness_weight: float = 0.20
    # 向量兜底相似度阈值
    vector_fallback_threshold: float = 0.85
    # 衰减豁免系数
    decay_exemption_strong: float = 0.1    # preference/identity/aversion
    decay_exemption_medium: float = 0.5    # habit/goal/capability

    # LLM 降级策略
    llm_fallback_enabled: bool = True  # LLM 不可用时是否降级到纯正则
    llm_timeout_seconds: float = 2.0   # LLM 调用超时
```

权重调整：原 5 因子权重总和为 1.0，加入 explicitness 后需重新分配：

```python
# 原权重
weights = {"emotion": 0.25, "novelty": 0.20, "goal_relevance": 0.25,
           "outcome_impact": 0.20, "rehearsal": 0.10}

# 新权重（explicitness 从各因子等比分摊）
weights = {"emotion": 0.20, "novelty": 0.16, "goal_relevance": 0.20,
           "outcome_impact": 0.16, "rehearsal": 0.08, "explicitness": 0.20}
```

---

## 7. API 端点设计说明

显式检测优化**复用现有 API**，不新增端点。架构文档定义的 13 个 API 端点（见 [03-consolidation-skill-policy-api.md](./memory-system/03-consolidation-skill-policy-api.md) 第 10 章）完全覆盖显式检测的需求：

| 现有端点 | 显式检测复用方式 |
|---|---|
| `POST /memory/write` | 显式检测在写入内部触发，API 不变 |
| `GET /memory/{memory_id}` | 返回的 memory 包含 explicit_* 字段 |
| `PUT /memory/{memory_id}` | 编辑时可修改 explicit_* 字段 |
| `GET /memory/graph/{user_id}` | 图可视化展示 superseded 记忆（灰色 + SUPERSEDED_BY 边） |
| `GET /memory/digest/{user_id}` | Digest 包含分组渲染的用户画像 |
| `DELETE /memory/{memory_id}` | 软删除（复用现有 is_active=false 机制） |

**不新增 API 端点**，所有显式检测逻辑在服务层内部完成。

---

## 8. 用户视角全链路调用图

```text
┌─────────────────────────────────────────────────────────────────────┐
│ 用户视角：从说出一句话到记忆被存储/检索/更新的完整链路              │
└─────────────────────────────────────────────────────────────────────┘

用户在对话中发送消息
  │  "我喜欢吃菠萝"
  │
  ▼
┌──────────────────────────────────────────┐
│ AssistantAgentService                    │
│ 1. 调用 LLM 生成回复                      │
│ 2. 对话结束后异步触发记忆写入             │
│    MemoryWriteService.write_from_        │
│    event(event)                          │
└──────────────────┬───────────────────────┘
                   │
                   ▼
┌──────────────────────────────────────────┐
│ ① ExplicitStatementDetector（新增）       │
│                                          │
│ 步骤 1: 正则预筛（零 LLM）                │
│   "我喜欢吃菠萝" → 命中 preference 类      │
│   命中模式: r"我(?:很|最|特别)?(?:喜欢)"  │
│                                          │
│ 步骤 2: LLM 确认（1 次轻量调用）           │
│   输入: 命中片段 + 上下文                  │
│   输出: {                                 │
│     is_explicit: true,                   │
│     category: "preference",              │
│     subject: "菠萝",                     │
│     polarity: "positive",                │
│     confidence: 0.95,                    │
│     summary: "用户喜欢吃菠萝",            │
│     temporal_marker: false               │
│   }                                      │
└──────────────────┬───────────────────────┘
                   │
                   │ confidence=0.95 ≥ 0.85 → 快路径
                   ▼
┌──────────────────────────────────────────┐
│ ② WriteTimeConflictResolver（新增）       │
│                                          │
│ 查询: 同用户 + preference 类 +            │
│       subject="菠萝" + is_active=true     │
│       + t_invalidated_at IS NULL          │
│                                          │
│ ┌─ Cypher 查询 Neo4j ──────────────────┐ │
│ │ MATCH (e:MemoryNode {user_id: $uid,  │ │
│ │   type: 'episode',                   │ │
│ │   explicit_category: 'preference',   │ │
│ │   explicit_subject: '菠萝',          │ │
│ │   is_active: true})                  │ │
│ │ WHERE e.t_invalidated_at IS NULL     │ │
│ │ RETURN e                             │ │
│ └──────────────────────────────────────┘ │
│                                          │
│ 结果: 无匹配（首次提到菠萝）               │
│ → 直接写入，无需 SUPERSEDE                │
└──────────────────┬───────────────────────┘
                   │
                   ▼
┌──────────────────────────────────────────┐
│ ③ LedgerWriter.write_full_path()         │
│                                          │
│ Neo4j 写入（Episode + Entity + 关系边）： │
│                                          │
│   // 1. 创建 Episode 节点                 │
│   CREATE (e:MemoryNode {                 │
│     type: 'episode',                     │
│     content: "用户喜欢吃菠萝",            │
│     explicit_category: "preference",     │
│     explicit_subject: "菠萝",            │
│     explicit_polarity: "positive",       │
│     is_active: true,                     │
│     t_invalidated_at: NULL,              │
│     created_at: ...                      │
│   })                                     │
│                                          │
│   // 2. 实体消解（三信号融合）             │
│   //    subject="菠萝" 作为种子           │
│   //    向量 + BM25 + LLM → MERGE        │
│   MERGE (ent:MemoryNode {                │
│     type: 'entity', name: '菠萝',        │
│     user_id: $uid                        │
│   })                                     │
│                                          │
│   // 3. 创建关系边                        │
│   CREATE (e)-[:MENTIONS {                │
│     weight: 1.0,                         │
│     t_valid_at: datetime()               │
│   }]->(ent)                              │
│                                          │
│ pgvector 写入:                            │
│   INSERT INTO user_memory (              │
│     memory_type, content, embedding,     │
│     metadata_, ...                       │
│   ) VALUES (                             │
│     'episode',                           │
│     "用户喜欢吃菠萝",                     │
│     <1536维向量>,                        │
│     {"detection": {...}},                │
│     ...                                  │
│   )                                      │
└──────────────────┬───────────────────────┘
                   │
                   ▼
┌──────────────────────────────────────────┐
│ 写入完成，返回结果给用户（无感知）          │
│                                          │
│ 用户后续提问: "帮我推荐水果"              │
│                   │                      │
│                   ▼                      │
│ MemoryRetriever.search()                 │
│   向量检索 user_memory                    │
│   WHERE t_invalidated_at IS NULL         │
│   → 返回 "用户喜欢吃菠萝"                 │
│                   │                      │
│                   ▼                      │
│ DigestManager.build_digest()             │
│   按 category + polarity 分组渲染         │
│   【偏好】喜欢吃菠萝                      │
│                   │                      │
│                   ▼                      │
│ LLM 拿到记忆上下文，推荐菠萝相关内容       │
└──────────────────────────────────────────┘


─── 偏好变化场景 ───────────────────────────────────────────────────

用户后续说: "我讨厌吃菠萝了"
  │
  ▼
① ExplicitStatementDetector
   → category=aversion, subject=菠萝, polarity=negative,
     confidence=0.92, temporal_marker=true
  │
  ▼
② WriteTimeConflictResolver
   Cypher 查到: e.explicit_subject="菠萝", polarity="positive",
               is_active=true, t_invalidated_at IS NULL
   极性比较: positive(旧) vs negative(新) → 反极性
   temporal_marker=true → 确认 SUPERSEDE
  │
  ▼
③ SUPERSEDE 操作（复用四时间戳模型，双写最终一致）
   Neo4j:
     旧节点 SET t_invalidated_at=datetime(), invalidated_by=新id,
                   is_active=false
     CREATE (旧)-[:SUPERSEDED_BY {
       t_valid_at: datetime(),
       t_transaction_start: datetime()
     }]->(新)
   pgvector:
     UPDATE user_memory SET t_invalidated_at=NOW(),
                            invalidated_by=新id,
                            embedding=NULL
     WHERE id=旧记忆id
   新记忆写入 Neo4j + pgvector (polarity=negative)
  │
  ▼
用户提问: "帮我推荐水果"
   → 检索只返回 t_invalidated_at IS NULL 的记忆
   → 返回 "用户讨厌菠萝"（不再推荐菠萝）

   DigestManager 更新:
   【偏好】喜欢吃苹果（菠萝已从偏好移除）
   【厌恶】讨厌菠萝
```

---

## 9. 管理员视角全链路调用图

```text
┌─────────────────────────────────────────────────────────────────────┐
│ 管理员视角：记忆系统的监控和调优全链路（不处理用户记忆内容）        │
└─────────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────┐
│ 管理员入口                                                       │
│                                                                  │
│  ┌──────────────┐  ┌──────────────┐                             │
│  │ 记忆监控面板  │  │ 配置调优面板  │                             │
│  └──────┬───────┘  └──────┬───────┘                             │
└─────────┼──────────────────┼─────────────────────────────────────┘
          │                  │
          ▼                  ▼
┌─────────────────┐ ┌─────────────────────┐
│ 记忆监控         │ │ 配置调优             │
│                 │ │                     │
│ 查看:           │ │ 调整:               │
│ · 用户记忆统计   │ │ · 检测阈值           │
│ · 显式记忆占比   │ │ · 衰减豁免系数        │
│ · 按类别分布     │ │ · 正则模式库          │
│ · 按极性分布     │ │ · LLM 模型选择        │
│ · 衰减状态       │ │ · LLM 降级开关        │
│ · 降级模式占比   │ │                     │
│                 │ │ 操作:               │
│ 操作:           │ │ · 新增/编辑正则模式    │
│ · 手动触发       │ │ · 启用/禁用检测类别    │
│   consolidation │ │ · 调整置信度阈值       │
│ · 导出用户记忆   │ │ · 调整权重分配         │
│   统计报告       │ │                     │
└────────┬────────┘ └──────────┬──────────┘
         │                     │
         ▼                     ▼
┌─────────────────────────────────────────────────────────────────┐
│ 后端服务层                                                       │
│                                                                 │
│  ┌──────────────────────┐  ┌──────────────────────────────┐    │
│  │ ConsolidationEngine   │  │ ConflictDetector（批量）      │    │
│  │                      │  │                              │    │
│  │ 触发方式:            │  │ 触发方式:                    │    │
│  │ · 管理员手动          │  │ · consolidation 时自动        │    │
│  │ · Celery 定时任务     │  │                              │    │
│  │                      │  │ 优化（新增）:                 │    │
│  │ 职责:                │  │ · 跳过已有 SUPERSEDED_BY 边   │    │
│  │ · 情节→语义记忆转化   │  │ · 跳过同 subject 已处理对     │    │
│  │ · 合并相似记忆        │  │ · 只处理写时检测遗漏的冲突    │    │
│  │ · 冷记忆归档          │  │ · 自动修复双写不一致          │    │
│  │ · 触发批量冲突检测    │  │                              │    │
│  └──────────┬───────────┘  └──────────────┬───────────────┘    │
│             │                             │                    │
│             ▼                             ▼                    │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │ MetricsCollector（监控指标）                               │  │
│  │                                                          │  │
│  │ 新增指标:                                                 │  │
│  │ · explicit_detection_total（检测总数）                    │  │
│  │ · explicit_detection_hit_rate（命中率）                   │  │
│  │ · explicit_fast_path_count（快路径写入数）                │  │
│  │ · explicit_boost_path_count（因子拉高数）                 │  │
│  │ · explicit_fallback_count（降级模式数）                   │  │
│  │ · write_time_supersede_count（写时 supersede 数）         │  │
│  │ · write_time_complement_count（写时共存数）               │  │
│  │ · conflict_detector_skipped_pairs（批量跳过对数）         │  │
│  │ · decay_exemption_count（衰减豁免数）                     │  │
│  │ · double_write_inconsistency_count（双写不一致数）        │  │
│  └──────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
          │
          ▼
┌─────────────────────────────────────────────────────────────────┐
│ 数据层（管理员只读监控，不操作用户记忆内容）                      │
│                                                                 │
│  ┌─────────────────┐  ┌─────────────────┐  ┌───────────────┐  │
│  │ Neo4j           │  │ pgvector        │  │ Redis         │  │
│  │                 │  │                 │  │               │  │
│  │ 管理员监控:      │  │ 管理员监控:      │  │ 管理员监控:    │  │
│  │ · 全图统计       │  │ · 用户记忆统计   │  │ · 访问计数器   │  │
│  │ · 冲突边数量     │  │ · supersede 统计 │  │ · 缓存命中率   │  │
│  │ · 衰减权重分布   │  │ · 按类别/极性    │  │ · 降级模式计数 │  │
│  │ · 层级分布       │  │   统计记忆       │  │               │  │
│  │                 │  │                 │  │               │  │
│  │ 双写一致性修复   │  │ 双写一致性修复   │  │               │  │
│  │ （consolidation  │  │ （consolidation  │  │               │  │
│  │  自动执行）:     │  │  自动执行）:     │  │               │  │
│  │ · 扫描           │  │ · 修正           │  │               │  │
│  │   t_invalidated  │  │   不一致状态     │  │               │  │
│  │   但 pgvector    │  │                 │  │               │  │
│  │   未同步的记忆   │  │                 │  │               │  │
│  └─────────────────┘  └─────────────────┘  └───────────────┘  │
│                                                                 │
│  注：管理员不处理用户记忆内容，仅监控系统健康度和调优配置。       │
│  双写不一致由 consolidation 自动修复，无需管理员干预。            │
└─────────────────────────────────────────────────────────────────┘
```

---

## 10. 实现路线

### Phase 1：核心检测与写入（最小可用）

| 任务 | 文件 | 说明 |
|---|---|---|
| 新建 ExplicitStatementDetector | `explicit_detector.py` | 正则预筛 + LLM 确认 + 降级策略 |
| 新建 WriteTimeConflictResolver | `write_time_conflict_resolver.py` | 极性比较 + SUPERSEDE（复用四时间戳模型） |
| 修改 MemoryWriteService | `memory_write_service.py` | 插入前置检测层 + 三层决策调用链 |
| 扩展 LedgerWriter | `ledger_writer.py` | 携带 explicit_* 属性 + 实体消解种子集成 |
| 扩展 MemoryVectorService | `memory_vector_service.py` | 写入 detection metadata |
| 扩展 SalienceScorer | `salience_scorer.py` | 新增 explicitness 因子 + 6 因子加权求和公式 |
| 扩展配置 | `memory_settings.py` | ExplicitDetectionConfig（含降级配置） |

### Phase 2：连锁优化

| 任务 | 文件 | 说明 |
|---|---|---|
| HebbianDecay 豁免 | `hebbian_decay.py` | 显式记忆 lambda_decay 豁免系数 |
| ConflictDetector 优化 | `conflict_detector.py` | 跳过已处理对 + 自动修复双写不一致 |
| Retriever 过滤增强 | `retriever.py` | 按 t_invalidated_at IS NULL 过滤 |
| DigestManager 分组渲染 | `digest_manager.py` | 按 category + polarity 分组渲染用户画像 |
| SkillEmergence 种子提示 | `skill_emergence.py` | register_seed_hint（不直接创建 Skill） |
| MetricsCollector 扩展 | `metrics.py` | 新增检测指标 + 降级模式指标 |

### Phase 3：图可视化（可选）

| 任务 | 说明 |
|---|---|
| superseded 记忆展示 | 灰色节点 + SUPERSEDED_BY 虚线边 + 历史记忆切换 |
| 用户图可视化扩展 | 用户可查看自己的记忆变化轨迹（只读） |

---

## 11. 测试策略

| 测试类别 | 覆盖场景 |
|---|---|
| **正则匹配测试** | 7 类模式各 10+ 正例/负例 |
| **LLM 确认测试** | mock LLM 返回，验证置信度分流 |
| **写时冲突测试** | 同极性共存、反极性 supersede、时态标记 |
| **双写一致性测试** | Neo4j 成功 + pgvector 失败的降级 |
| **衰减豁免测试** | 显式记忆 lambda_decay 豁免系数验证 |
| **LLM 降级测试** | LLM 超时/不可用时的纯正则降级模式 |
| **实体消解集成测试** | 显式 subject 作为种子，避免重复创建实体 |
| **SalienceScorer 6 因子测试** | explicitness=0.0/0.8/1.0 的评分验证 + 阈值路由 |
| **SkillEmergence 种子提示测试** | 种子提示降低频次阈值的验证 |
| **DigestManager 分组渲染测试** | 按 category + polarity 分组渲染验证 |
| **端到端测试** | T1→T2→T3→T4 完整流转验证 |
