import { get, post, del, request } from '@/utils/request'
import { type BaseResponse } from '@/models/base'

const patch = <T>(url: string, body?: Record<string, unknown>) =>
  request<T>(url, { method: 'PATCH', body })

export type SubPoolType = 'agent' | 'tool'

export interface SubPoolDefinition {
  id: string
  pool_type: SubPoolType
  name: string
  label: string
  description: string
  visible_to_user: boolean
  default_enabled: boolean
  default_capabilities: string[]
  task_keywords: string[]
  sort_order: number
  is_system: boolean
  enabled: boolean
  created_at?: number
  updated_at?: number
}

export type SubPoolDefinitionListData = {
  list: SubPoolDefinition[]
  paginator: {
    current_page: number
    page_size: number
    total_record: number
    total_page: number
  }
}

export type ListSubPoolDefinitionsParams = {
  pool_type?: SubPoolType | ''
  enabled?: boolean | ''
  keyword?: string
  current_page?: number
  page_size?: number
}

export type CreateSubPoolDefinitionPayload = {
  pool_type: SubPoolType
  name: string
  label: string
  description?: string
  visible_to_user: boolean
  default_enabled: boolean
  default_capabilities: string[]
  task_keywords: string[]
  sort_order: number
}

export type UpdateSubPoolDefinitionPayload = Partial<CreateSubPoolDefinitionPayload>

export const listSubPoolDefinitions = (params?: ListSubPoolDefinitionsParams) =>
  get<BaseResponse<SubPoolDefinitionListData>>('/admin/sub-pool-definitions', { params })

export const createSubPoolDefinition = (data: CreateSubPoolDefinitionPayload) =>
  post<BaseResponse<SubPoolDefinition>>('/admin/sub-pool-definitions', { body: data })

export const getSubPoolDefinition = (id: string) =>
  get<BaseResponse<SubPoolDefinition>>(`/admin/sub-pool-definitions/${id}`)

export const updateSubPoolDefinition = (id: string, data: UpdateSubPoolDefinitionPayload) =>
  patch<BaseResponse<SubPoolDefinition>>(`/admin/sub-pool-definitions/${id}`, data)

export const deleteSubPoolDefinition = (id: string) =>
  del<BaseResponse<Record<string, unknown>>>(`/admin/sub-pool-definitions/${id}`)

export const setSubPoolDefinitionStatus = (id: string, enabled: boolean) =>
  post<BaseResponse<Record<string, unknown>>>(`/admin/sub-pool-definitions/${id}/status`, {
    body: { enabled },
  })
