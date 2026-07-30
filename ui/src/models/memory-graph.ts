// 记忆图谱前端类型定义

// 记忆节点
export type MemoryNode = {
  id: string
  memory_type: string
  content: string
  confidence: number
  weight: number
  tier: 'HOT' | 'WARM' | 'COLD'
  is_active: boolean
  created_at: string
  last_accessed_at?: string
  source_conversation_id?: string
  metadata?: Record<string, unknown>
}

// 记忆边
export type MemoryEdge = {
  source: string
  target: string
  type: string
  weight: number
}

// 聚类摘要
export type MemoryCluster = {
  memory_type: string
  node_count: number
  last_updated_at: string
}

// 图谱总览数据
export type MemoryGraphData = {
  user_id: string
  clusters: MemoryCluster[]
  total_nodes: number
}

// 聚类子图
export type ClusterSubgraph = {
  nodes: MemoryNode[]
  edges: MemoryEdge[]
  truncated: boolean
}

// 关联节点
export type RelatedNode = {
  node_id: string
  weight: number
  relation: string
}

// 记忆详情
export type MemoryDetail = {
  memory_id: string
  content: string
  memory_type?: string
  confidence?: number
  source_conversation_id?: string
  created_at?: string
  last_accessed_at?: string
  related: RelatedNode[]
}

// 技能状态
export type SkillStatus = 'candidate' | 'emerging' | 'active' | 'stale' | 'deprecated'

// 技能信息
export type SkillInfo = {
  skill_id?: string
  name: string
  description?: string
  template?: string
  parameters?: Array<{ name: string; type: string; description: string }>
  status: SkillStatus
  maturity?: number
  use_count?: number
  frequency?: number
  first_seen_at?: string
  last_used_at?: string
  last_updated_at?: string
  cached?: boolean
}

// 技能列表响应
export type SkillListResponse = {
  user_id: string
  skills: SkillInfo[]
  total: number
}

// 记忆写入请求
export type MemoryWriteReq = {
  content: string
  memory_type?: string
}

// 记忆写入响应
export type MemoryWriteResp = {
  status: string
  memory_id: string | null
  created_at: string
  score: number
  entity_count: number | null
  edge_count: number | null
  vector_id: string | null
}

// 记忆检索请求
export type MemoryRetrieveReq = {
  query: string
  top_k?: number
  time_range_days?: number
  budget_tokens?: number
}

// 检索结果项
export type RetrievalResultItem = {
  memory_id?: string
  content: string
  memory_type?: string
  score?: number
  weight?: number
  source?: string
}

// 记忆检索响应
export type MemoryRetrieveResp = {
  results: RetrievalResultItem[]
  summary: string | null
  intent: string | null
  retrieval_path: string
  latency_ms: number
}

// 记忆 Digest 响应
export type MemoryDigestResp = {
  user_id: string
  digest: string
  cached: boolean
}

// 巩固响应
export type ConsolidationResp = {
  user_id: string
  success: boolean
  total_items: number
  phase_results: Record<string, unknown>
  errors: string[]
  task_id: string | null
}

// 编辑记忆响应
export type EditMemoryResp = {
  success: boolean
  new_memory_id?: string
  error?: string
}

// 删除记忆响应
export type DeleteMemoryResp = {
  deleted: boolean
}

// 降权响应
export type DecayMemoryResp = {
  memory_id: string
  new_weight: number
}

// 健康检查响应
export type MemoryHealth = {
  status: string
  version: string
  neo4j: string
  pgvector: string
  redis: string
  uptime_seconds: number
}
