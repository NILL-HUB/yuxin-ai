import { del, get, post, request } from '@/utils/request'
import type {
  CreateApiToolProviderRequest,
  GetApiToolProviderResponse,
  GetApiToolProvidersWithPageResponse,
  UpdateApiToolProviderRequest,
} from '@/models/api-tool'
import type { BaseResponse } from '@/models/base'

export type GetAdminApiToolsParams = {
  current_page: number
  page_size: number
  search_word?: string
}

export type AdminApiToolPageData = GetApiToolProvidersWithPageResponse['data']

/**
 * 获取后台 API 工具分页列表，并解包接口返回的 data 字段。
 */
export const listAdminApiTools = async (
  params: GetAdminApiToolsParams,
): Promise<AdminApiToolPageData> => {
  const response = await get<GetApiToolProvidersWithPageResponse>('/admin/api-tools', { params })
  return response.data
}

/**
 * 创建后台 API 工具 Provider。
 */
export const createAdminApiTool = async (
  body: CreateApiToolProviderRequest,
): Promise<GetApiToolProviderResponse['data']> => {
  const response = await post<GetApiToolProviderResponse>('/admin/api-tools', { body })
  return response.data
}

/**
 * 获取单个后台 API 工具 Provider 详情。
 */
export const getAdminApiTool = async (
  id: string,
): Promise<GetApiToolProviderResponse['data']> => {
  const response = await get<GetApiToolProviderResponse>(`/admin/api-tools/${id}`)
  return response.data
}

/**
 * 更新后台 API 工具 Provider。
 */
export const updateAdminApiTool = async (
  id: string,
  body: UpdateApiToolProviderRequest,
): Promise<GetApiToolProviderResponse['data']> => {
  const response = await request<GetApiToolProviderResponse>(`/admin/api-tools/${id}`, {
    method: 'PATCH',
    body,
  })
  return response.data
}

/**
 * 删除后台 API 工具 Provider。
 */
export const deleteAdminApiTool = async (id: string): Promise<Record<string, never>> => {
  const response = await del<BaseResponse<Record<string, never>>>(`/admin/api-tools/${id}`)
  return response.data
}
