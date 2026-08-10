import { del, get, post } from '@/utils/request'
import type { BaseResponse } from '@/models/base'
import type {
  AdminDocumentsPageData,
  AdminHitTestItem,
  AdminHitTestRequest,
  AdminHitTestResponse,
  AdminKnowledgeDocument,
  CreateSystemKnowledgeRequest,
  GetAdminDocumentsRequest,
  GetSystemKnowledgeRequest,
  SystemKnowledgeDetailResponse,
  SystemKnowledgePageData,
  SystemKnowledgePageResponse,
  SystemKnowledgeRecord,
  UpdateSystemKnowledgeRequest,
} from '@/models/admin-system-knowledge'

/**
 * 获取系统知识库列表，并解包接口返回的 data 字段。
 */
export const listSystemKnowledge = async (
  req: GetSystemKnowledgeRequest,
): Promise<SystemKnowledgePageData> => {
  const response = await get<SystemKnowledgePageResponse>('/admin/system-knowledge', { params: req })
  return response.data
}

/**
 * 创建系统知识库，返回新建记录。
 */
export const createSystemKnowledge = async (
  req: CreateSystemKnowledgeRequest,
): Promise<SystemKnowledgeRecord> => {
  const response = await post<SystemKnowledgeDetailResponse>('/admin/system-knowledge', { body: req })
  return response.data
}

/**
 * 获取系统知识库详情。
 */
export const getSystemKnowledge = async (
  id: string,
): Promise<SystemKnowledgeRecord> => {
  const response = await get<SystemKnowledgeDetailResponse>(`/admin/system-knowledge/${id}`)
  return response.data
}

/**
 * 更新系统知识库，返回更新后的记录。
 */
export const updateSystemKnowledge = async (
  id: string,
  req: UpdateSystemKnowledgeRequest,
): Promise<SystemKnowledgeRecord> => {
  const response = await post<SystemKnowledgeDetailResponse>(`/admin/system-knowledge/${id}`, {
    body: req,
  })
  return response.data
}

/**
 * 删除系统知识库（进入回收站，retention_days 为留存天数：7/30/90/180）。
 */
export const deleteSystemKnowledge = async (
  id: string,
  retentionDays?: number,
): Promise<void> => {
  await del<BaseResponse<{ id: string }>>(`/admin/system-knowledge/${id}`, {
    body: retentionDays ? { retention_days: retentionDays } : undefined,
  })
}

/**
 * 获取系统知识库内文档分页列表。
 * 后端返回 PageModel{list, paginator}，此处转换为 items + total_record 结构。
 */
export const listAdminKnowledgeDocuments = async (
  knowledgeBaseId: string,
  req: GetAdminDocumentsRequest,
): Promise<AdminDocumentsPageData> => {
  const response = await get<BaseResponse<{
    list: AdminKnowledgeDocument[]
    paginator: { total_record: number; total_page: number; current_page: number; page_size: number }
  }>>(
    `/admin/system-knowledge/${knowledgeBaseId}/documents`,
    { params: req },
  )
  const raw = response.data || ({} as never)
  const items = Array.isArray(raw.list) ? raw.list : []
  const paginator = raw.paginator || {}
  return {
    items,
    total: paginator.total_record ?? items.length,
    page: paginator.current_page ?? req.current_page,
    page_size: paginator.page_size ?? req.page_size,
    total_pages: paginator.total_page ?? 0,
    total_record: paginator.total_record ?? items.length,
  }
}

/**
 * 上传文档到系统知识库（单文件，后端自动解析与索引，返回新建文档 id）。
 */
export const uploadAdminKnowledgeDocument = (
  knowledgeBaseId: string,
  file: File,
): Promise<BaseResponse<{ id: string; name: string }>> => {
  const formData = new FormData()
  formData.append('file', file)
  return post<BaseResponse<{ id: string; name: string }>>(
    `/admin/system-knowledge/${knowledgeBaseId}/documents/upload`,
    { body: formData },
  )
}

/**
 * 获取系统知识库内单个文档详情（上传后轮询索引状态用）。
 */
export const getAdminKnowledgeDocument = async (
  knowledgeBaseId: string,
  documentId: string,
): Promise<AdminKnowledgeDocument> => {
  const response = await get<BaseResponse<AdminKnowledgeDocument>>(
    `/admin/system-knowledge/${knowledgeBaseId}/documents/${documentId}`,
  )
  return response.data
}

/**
 * 以纯文本新建系统知识库文档（内容按 txt 走完整索引链路）。
 */
export const createAdminTextDocument = (
  knowledgeBaseId: string,
  name: string,
  content: string,
): Promise<BaseResponse<{ id: string; name: string }>> => {
  return post<BaseResponse<{ id: string; name: string }>>(
    `/admin/system-knowledge/${knowledgeBaseId}/documents/text`,
    { body: { name, content } },
  )
}

/**
 * 编辑系统知识库文档（重建内容索引，保持文档 id 不变）。
 */
export const updateAdminTextDocument = (
  knowledgeBaseId: string,
  documentId: string,
  name: string,
  content: string,
): Promise<BaseResponse<{ id: string; name: string }>> => {
  return post<BaseResponse<{ id: string; name: string }>>(
    `/admin/system-knowledge/${knowledgeBaseId}/documents/${documentId}`,
    { body: { name, content } },
  )
}

/**
 * 删除系统知识库内指定文档（进入回收站，可指定留存天数）。
 */
export const deleteAdminKnowledgeDocument = async (
  knowledgeBaseId: string,
  documentId: string,
  retentionDays?: number,
): Promise<void> => {
  await del<BaseResponse<{ id: string }>>(
    `/admin/system-knowledge/${knowledgeBaseId}/documents/${documentId}`,
    {
      body: retentionDays ? { retention_days: retentionDays } : undefined,
    },
  )
}

/**
 * 获取系统知识库文档下的分段列表（编辑时拼接原内容用）。
 * 后端返回 PageModel{list, paginator}。
 */
export const listAdminDocumentSegments = async (
  knowledgeBaseId: string,
  documentId: string,
  current_page: number,
  page_size: number,
): Promise<{
  list: Array<{ id: string; position: number; content: string }>
  paginator: { total_record: number }
}> => {
  const response = await get<BaseResponse<{
    list: Array<{ id: string; position: number; content: string }>
    paginator: { total_record: number }
  }>>(
    `/admin/system-knowledge/${knowledgeBaseId}/documents/${documentId}/segments`,
    { params: { current_page, page_size } },
  )
  const raw = response.data || ({} as never)
  return {
    list: Array.isArray(raw.list) ? raw.list : [],
    paginator: raw.paginator || { total_record: 0 },
  }
}

/**
 * 系统知识库命中测试（输入问题预览检索结果）。
 */
export const hitTestAdminKnowledge = async (
  knowledgeBaseId: string,
  req: AdminHitTestRequest,
): Promise<AdminHitTestItem[]> => {
  const response = await post<AdminHitTestResponse>(
    `/admin/system-knowledge/${knowledgeBaseId}/hit-test`,
    { body: req },
  )
  return response.data
}
