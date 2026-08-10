"""数据集模型兼容层：数据集相关模型已合并至 knowledge 模块，保留 dataset 命名以兼容既有引用。"""

from internal.model.knowledge import (
    KnowledgeBase as Dataset,
    KnowledgeDocument as Document,
    KnowledgeSegment as Segment,
)
