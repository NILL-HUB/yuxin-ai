import { del, get, post, request } from '@/utils/request'
import type {
  CreateMcpProviderRequest,
  GetMcpProviderResponse,
  GetMcpProvidersWithPageRequest,
  GetMcpProvidersWithPageResponse,
  UpdateMcpProviderRequest,
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
 * 获取后台 MCP Provider 详情（管理员视角，不校验账号归属）。
 * 返回结构与 mcp.ts 的 getMcpProvider 保持一致，便于复用模态框。
 */
export const getAdminMcp = (id: string) => {
  return get<GetMcpProviderResponse>(`/admin/mcp/${id}`)
}

/**
 * 更新后台 MCP Provider（管理员视角，不校验账号归属）。
 * 返回结构与 mcp.ts 的 updateMcpProvider 保持一致。
 */
export const updateAdminMcp = (id: string, body: UpdateMcpProviderRequest) => {
  return request<BaseResponse<any>>(`/admin/mcp/${id}`, {
    method: 'PATCH',
    body,
  })
}

/**
 * 重新生成后台 MCP Provider 图标（管理员视角，不校验账号归属）。
 * 返回结构与 mcp.ts 的 regenerateMcpIcon 保持一致。
 */
export const regenerateAdminMcpIcon = (id: string) => {
  return post<BaseResponse<{ icon: string }>>(`/admin/mcp/${id}/regenerate-icon`)
}

/**
 * 删除后台 MCP Provider。
 */
export const deleteAdminMcp = async (id: string): Promise<Record<string, never>> => {
  const response = await del<BaseResponse<Record<string, never>>>(`/admin/mcp/${id}`)
  return response.data
}
