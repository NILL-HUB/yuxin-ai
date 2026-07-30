import { del, get, post } from '@/utils/request'
import type { BaseResponse } from '@/models/base'
import type {
  CreateSystemKnowledgeRequest,
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
 * 删除系统知识库。
 */
export const deleteSystemKnowledge = async (id: string): Promise<void> => {
  await del<BaseResponse<{ id: string }>>(`/admin/system-knowledge/${id}`)
}
