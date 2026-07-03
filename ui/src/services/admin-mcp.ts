import { del, get, post } from '@/utils/request'
import type {
  CreateMcpProviderRequest,
  GetMcpProviderResponse,
  GetMcpProvidersWithPageRequest,
  GetMcpProvidersWithPageResponse,
} from '@/models/mcp'
import type { BaseResponse } from '@/models/base'

/**
 * 获取后台 MCP Provider 分页列表，并解包接口返回的 data 字段。
 */
export const listAdminMcpProviders = async (
  params: GetMcpProvidersWithPageRequest,
): Promise<GetMcpProvidersWithPageResponse['data']> => {
  const response = await get<GetMcpProvidersWithPageResponse>('/admin/mcp', { params })
  return response.data
}

/**
 * 创建后台 MCP Provider。
 */
export const createAdminMcp = async (
  body: CreateMcpProviderRequest,
): Promise<GetMcpProviderResponse['data']> => {
  const response = await post<GetMcpProviderResponse>('/admin/mcp', { body })
  return response.data
}

/**
 * 删除后台 MCP Provider。
 */
export const deleteAdminMcp = async (id: string): Promise<Record<string, never>> => {
  const response = await del<BaseResponse<Record<string, never>>>(`/admin/mcp/${id}`)
  return response.data
}
