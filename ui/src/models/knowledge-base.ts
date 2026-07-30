import { type BasePaginatorResponse, type BaseResponse } from '@/models/base'

// 获取用户端知识库分页列表接口响应结构
export type GetKnowledgeBasesWithPageResponse = BasePaginatorResponse<{
  id: string
  name: string
  icon: string
  description: string
  document_count: number
  character_count: number
  creator_name: string
  creator_avatar: string
  embedding_model_id?: string
  updated_at: number
  created_at: number
}>

// 新增知识库请求结构
// embedding_model_id 由后端自动选择（维度优先+健康度），用户不能自选
export type CreateKnowledgeBaseRequest = {
  name: string
  icon: string
  description: string
}

// 更新知识库请求结构
// embedding_model_id 不允许用户端修改，避免维度错位导致整个知识库向量失效
export type UpdateKnowledgeBaseRequest = {
  name: string
  icon: string
  description: string
}

// 获取知识库详情响应结构
export type GetKnowledgeBaseResponse = BaseResponse<{
  id: string
  icon: string
  name: string
  description: string
  document_count: number
  character_count: number
  embedding_model_id?: string
  updated_at: number
  created_at: number
}>

// 获取指定知识库文档列表分页请求结构
export type GetKnowledgeDocumentsWithPageRequest = {
  current_page: number
  page_size: number
  search_word: string
}

// 获取指定知识库文档分页列表响应结构
export type GetKnowledgeDocumentsWithPageResponse = BasePaginatorResponse<{
  id: string
  name: string
  character_count: number
  status: string
  error: string
  updated_at: number
  created_at: number
}>

// 获取指定文档详情响应结构
export type GetKnowledgeDocumentResponse = BaseResponse<{
  id: string
  knowledge_base_id: string
  name: string
  segment_count: number
  character_count: number
  status: string
  error: string
  updated_at: number
  created_at: number
}>

// 知识库召回测试请求结构
export type HitRequest = {
  retrieval_strategy: string
  k: number
  query: string
  score: number
}

// 知识库召回测试响应结构
export type HitResponse = BaseResponse<
  Array<{
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
    disabled_at: number
    status: string
    error: string
    updated_at: number
    created_at: number
  }>
>

// 获取指定文档的片段列表请求结构
export type GetKnowledgeSegmentsWithPageRequest = {
  current_page: number
  page_size: number
  search_word: string
}

// 获取指定文档的片段列表响应结构
export type GetKnowledgeSegmentsWithPageResponse = BasePaginatorResponse<{
  id: string
  knowledge_base_id: string
  knowledge_document_id: string
  position: number
  content: string
  keywords: string[]
  character_count: number
  token_count: number
  hit_count: number
  enabled: boolean
  status: string
  updated_at: number
  created_at: number
}>

// 修改文档片段请求结构（可同时更新启用状态与内容）
export type UpdateKnowledgeSegmentRequest = {
  enabled?: boolean
  content?: string
}
