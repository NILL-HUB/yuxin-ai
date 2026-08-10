import type { BaseResponse } from '@/models/base'

// 系统知识库记录
export type SystemKnowledgeRecord = {
  id: string
  name: string
  description: string
  knowledge_scope: string
  visibility_scope?: string
  owner_admin_user_id?: string | null
  creator_name?: string
  enabled: boolean
  document_count?: number
  character_count?: number
  updated_at: number | null
  created_at: number | null
}

// 系统知识库列表查询请求
export type GetSystemKnowledgeRequest = {
  page: number
  page_size: number
  search_word: string
}

// 创建系统知识库请求
export type CreateSystemKnowledgeRequest = {
  name: string
  description: string
  visibility_scope: string
}

// 更新系统知识库请求
export type UpdateSystemKnowledgeRequest = {
  name?: string
  description?: string
  visibility_scope?: string
  enabled?: boolean
}

// 系统知识库列表响应的数据部分（后端返回 items + 分页器字段，前端按服务端分页+搜索使用）
export type SystemKnowledgePageData = {
  items: SystemKnowledgeRecord[]
  // 兼容旧前端的 total 字段（值与 total_record 一致）
  total: number
  // 服务端分页器字段
  page: number
  page_size: number
  total_pages: number
  total_record: number
}

// 系统知识库列表响应
export type SystemKnowledgePageResponse = BaseResponse<SystemKnowledgePageData>

// 单条系统知识库响应
export type SystemKnowledgeDetailResponse = BaseResponse<SystemKnowledgeRecord>

// 系统知识库文档记录
export type AdminKnowledgeDocument = {
  id: string
  knowledge_base_id: string
  name: string
  segment_count?: number
  segment_character_count?: number
  character_count: number
  status: string
  error: string
  updated_at: number | null
  created_at: number | null
}

// 文档分页请求
export type GetAdminDocumentsRequest = {
  current_page: number
  page_size: number
  search_word: string
}

// 文档分页响应数据
export type AdminDocumentsPageData = {
  items: AdminKnowledgeDocument[]
  total: number
  page: number
  page_size: number
  total_pages: number
  total_record: number
}

export type AdminDocumentsPageResponse = BaseResponse<AdminDocumentsPageData>

// 命中测试请求
export type AdminHitTestRequest = {
  query: string
  retrieval_strategy: string
  k: number
  score: number
}

// 命中测试响应数据
export type AdminHitTestItem = {
  id: string
  document: {
    id: string
    name: string
    extension: string
    mime_type: string
  }
  knowledge_base_id: string
  score: number
  position: number
  content: string
  keywords: string[]
  character_count: number
  token_count: number
  hit_count: number
  enabled: boolean
  status: string
  updated_at: number | null
  created_at: number | null
}

export type AdminHitTestResponse = BaseResponse<AdminHitTestItem[]>
