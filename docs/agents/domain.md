# Domain Docs

这些工程技能在探索代码库时应如何阅读本仓库的领域文档。

## 本仓库的实际布局（权威）

本仓库为 **single-context** 布局，但**不使用** `CONTEXT.md` / `CONTEXT-MAP.md` / `docs/adr/` 这三个位置（与上游模板的默认约定不同）。领域事实的权威来源是：

- **[`docs/README.md`](../README.md)**——文档导航入口。**从这里开始**，它索引当前生效的全部架构与设计文档。
- **[`docs/prd/product-vision.md`](../prd/product-vision.md)**——产品形态与经代码验证的落地状态（产品问题的第一入口）。
- **[`docs/prd/architecture-design.md`](../prd/architecture-design.md)**——核心架构与模块设计。
- **[`docs/prd/modules/`](../prd/modules/)**——各子模块设计（Agent/工具池、知识库、编排、存储、安全、OS 自动化等）。
- **[`docs/prd/memory-system/`](../prd/memory-system/)**——记忆系统设计。
- **[`AGENTS.md`](../../AGENTS.md)**——本仓库的强制规则（含「架构文档同步」规则与文档映射表）。

探索代码库前，先读 `docs/README.md` 找到与当前主题相关的文档；`AGENTS.md` 是判断文档与代码冲突时该往哪写的依据。

> 上游技能若提到 `CONTEXT.md` / `CONTEXT-MAP.md` / `docs/adr/`，在本仓库中**一律映射为上表**。这些位置在本仓库不存在，凡引用它们的描述均为过时残留。

## 与上游模板的差异说明

上游通用模板（多仓库共用）默认假定：

```
/
├── CONTEXT.md
├── docs/adr/
└── src/
```

本仓库**未采用**该布局，而是把领域文档集中在 `docs/` 下并以 `docs/README.md` 作为唯一导航入口（与 `AGENTS.md` 的「架构文档同步」规则配套）。因此：

- 不需要、也不应创建 `CONTEXT.md` / `CONTEXT-MAP.md` / `docs/adr/`。
- 领域术语与决策的落点：术语/概念进 `docs/prd/` 对应文档；架构决策的诊断与演进进 `docs/prd/architecture-design.md` 与 `docs/prd/execution-roadmap.md`；长期废弃的规划移入 `docs/archive/`。

## 使用术语表的词汇

当输出中需要命名领域概念（issue 标题、重构提案、假设、测试名称）时，使用 `docs/prd/` 下文档中定义的既有说法（例如「板块」「分区」「素材」「向量化」等本仓库概念），不要漂移到同义词。

如果需要用到的概念还没出现在既有文档中，这是一个信号——要么你在发明项目不使用的语言（请重新考虑），要么确实存在缺口（记下来，按 `AGENTS.md` 的文档映射写入对应文档）。

## 标记决策冲突

如果输出与 `docs/prd/architecture-design.md` 或既有模块文档冲突，要明确指出来，而不是默默覆盖：

> _与 `docs/prd/modules/06-file-storage.md`（运行时代理分发）冲突——但值得重新讨论，因为…_

若发现文档描述与代码不符（引用已删除文件、声称未实现的功能已实现、模块已被取代但文档仍是主线叙事），按 `AGENTS.md`「架构文档同步（强制规则）」在完成代码后**立即修正文档**，不得保留过期内容。
