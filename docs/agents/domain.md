# Domain Docs

这些工程技能在探索代码库时应如何阅读本仓库的领域文档。

## 探索前先阅读

- **`CONTEXT.md`**（仓库根目录），或
- **`CONTEXT-MAP.md`**（仓库根目录，如果存在）——它指向每个 context 各自的 `CONTEXT.md`。阅读与当前主题相关的每一个文件。
- **`docs/adr/`**——阅读与你即将处理区域相关的 ADR。在多 context 仓库中，还要检查 `src/<context>/docs/adr/` 下的 context 级决策。

如果这些文件不存在，**静默继续**。不要强调缺失，也不要主动建议立即创建。`/domain-modeling` 技能（通过 `/grill-with-docs` 和 `/improve-codebase-architecture` 触达）会在术语或决策真正确定时惰性创建它们。

## 文件结构

Single-context 仓库（大多数仓库）：

```
/
├── CONTEXT.md
├── docs/adr/
│   ├── 0001-event-sourced-orders.md
│   └── 0002-postgres-for-write-model.md
└── src/
```

Multi-context 仓库（根目录存在 `CONTEXT-MAP.md` 时）：

```
/
├── CONTEXT-MAP.md
├── docs/adr/                          ← 系统级决策
└── src/
    ├── ordering/
    │   ├── CONTEXT.md
    │   └── docs/adr/                  ← context 级决策
    └── billing/
        ├── CONTEXT.md
        └── docs/adr/
```

## 使用术语表的词汇

当输出中需要命名领域概念（issue 标题、重构提案、假设、测试名称）时，使用 `CONTEXT.md` 中定义的说法。不要漂移到术语表明确避开的同义词。

如果需要用到的概念还没出现在术语表中，这是一个信号——要么你在发明项目不使用的语言（请重新考虑），要么确实存在缺口（记下来交给 `/domain-modeling`）。

## 标记 ADR 冲突

如果输出与现有 ADR 冲突，要明确指出来，而不是默默覆盖：

> _与 ADR-0007（event-sourced orders）冲突——但值得重新讨论，因为…_
