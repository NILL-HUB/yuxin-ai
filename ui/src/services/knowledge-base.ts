import { get, post } from '@/utils/request'
import { type BaseResponse } from '@/models/base'
import {
  type CreateKnowledgeBaseRequest,
  type GetKnowledgeBaseResponse,
  type GetKnowledgeBasesWithPageResponse,
  type GetKnowledgeDocumentResponse,
  type GetKnowledgeDocumentsWithPageRequest,
  type GetKnowledgeDocumentsWithPageResponse,
  type GetKnowledgeSegmentsWithPageRequest,
  type GetKnowledgeSegmentsWithPageResponse,
  type HitRequest,
  type HitResponse,
  type UpdateKnowledgeBaseRequest,
  type UpdateKnowledgeSegmentRequest,
} from '@/models/knowledge-base'

// 上传文档到知识库（单文件上传，后端自动完成解析与索引）
export const uploadKnowledgeDocument = (
  knowledge_base_id: string,
  file: File,
) => {
  const formData = new FormData()
  formData.append('file', file)
  return post<BaseResponse<Record<string, unknown>>>(
    `/space/knowledge-bases/${knowledge_base_id}/documents/upload`,
    {
      body: formData,
    },
  )
}

// 获取用户端知识库分页列表数据
export const getKnowledgeBasesWithPage = (
  current_page: number = 1,
  page_size: number = 20,
  search_word: string = '',
) => {
  return get<GetKnowledgeBasesWithPageResponse>(`/space/knowledge-bases`, {
    params: { current_page, page_size, search_word },
  })
}

// 新增用户端知识库
export const createKnowledgeBase = (req: CreateKnowledgeBaseRequest) => {
  return post<BaseResponse<Record<string, unknown>>>(`/space/knowledge-bases`, {
    body: req,
  })
}

// 更新用户端知识库
export const updateKnowledgeBase = (
  knowledge_base_id: string,
  req: UpdateKnowledgeBaseRequest,
) => {
  return post<BaseResponse<Record<string, unknown>>>(`/space/knowledge-bases/${knowledge_base_id}`, {
    body: req,
  })
}

// 删除用户端知识库
export const deleteKnowledgeBase = (knowledge_base_id: string) => {
  return post<BaseResponse<Record<string, unknown>>>(`/space/knowledge-bases/${knowledge_base_id}/delete`)
}

// 获取用户端知识库详情
export const getKnowledgeBase = (knowledge_base_id: string) => {
  return get<GetKnowledgeBaseResponse>(`/space/knowledge-bases/${knowledge_base_id}`)
}

// 知识库召回测试
export const hitKnowledgeBase = (knowledge_base_id: string, req: HitRequest) => {
  return post<HitResponse>(`/space/knowledge-bases/${knowledge_base_id}/hit`, {
    body: req,
  })
}

// 获取知识库下文档分页列表数据
export const getKnowledgeDocumentsWithPage = (
  knowledge_base_id: string,
  req: GetKnowledgeDocumentsWithPageRequest = {
    current_page: 1,
    page_size: 20,
    search_word: '',
  },
) => {
  return get<GetKnowledgeDocumentsWithPageResponse>(
    `/space/knowledge-bases/${knowledge_base_id}/documents`,
    {
      params: req,
    },
  )
}

// 获取知识库下指定文档详情
export const getKnowledgeDocument = (
  knowledge_base_id: string,
  document_id: string,
) => {
  return get<GetKnowledgeDocumentResponse>(
    `/space/knowledge-bases/${knowledge_base_id}/documents/${document_id}`,
  )
}

// 删除知识库下指定文档
export const deleteKnowledgeDocument = (
  knowledge_base_id: string,
  document_id: string,
) => {
  return post<BaseResponse<Record<string, unknown>>>(
    `/space/knowledge-bases/${knowledge_base_id}/documents/${document_id}/delete`,
  )
}

// 获取文档下片段分页列表
export const getKnowledgeSegmentsWithPage = (
  knowledge_base_id: string,
  document_id: string,
  req: GetKnowledgeSegmentsWithPageRequest,
) => {
  return get<GetKnowledgeSegmentsWithPageResponse>(
    `/space/knowledge-bases/${knowledge_base_id}/documents/${document_id}/segments`,
    {
      params: req,
    },
  )
}

// 更新文档片段内容或启用状态
export const updateKnowledgeSegment = (
  knowledge_base_id: string,
  document_id: string,
  segment_id: string,
  req: UpdateKnowledgeSegmentRequest,
) => {
  return post<BaseResponse<Record<string, unknown>>>(
    `/space/knowledge-bases/${knowledge_base_id}/documents/${document_id}/segments/${segment_id}`,
    { body: req },
  )
}

// 重新生成知识库图标
export const regenerateKnowledgeBaseIcon = (knowledge_base_id: string) => {
  return post<BaseResponse<{ icon: string }>>(
    `/space/knowledge-bases/${knowledge_base_id}/regenerate-icon`,
  )
}

// 生成知识库图标预览（不保存到知识库）
export const generateKnowledgeBaseIconPreview = (name: string, description: string) => {
  return post<BaseResponse<{ icon: string }>>(
    `/space/knowledge-bases/generate-icon-preview`,
    {
      body: { name, description },
    },
  )
}

// 列出对 Agent 可读的系统知识库（enabled=True），供 App 配置引用
// 用户对系统知识库只读，仅能在 App 配置中引用，无法编辑/删除
export const listReadableSystemKnowledgeBases = () => {
  return get<BaseResponse<{ list: Array<{ id: string; name: string; description: string; knowledge_scope: string }> }>>(
    '/space/system-knowledge-bases',
  )
}
