import { get } from '@/utils/request'
import type { GetMcpProvidersWithPageRequest, GetMcpProvidersWithPageResponse } from '@/models/mcp'

/**
 * 获取后台 MCP Provider 分页列表，并解包接口返回的 data 字段。
 */
export const listAdminMcpProviders = async (
  params: GetMcpProvidersWithPageRequest,
): Promise<GetMcpProvidersWithPageResponse['data']> => {
  const response = await get<GetMcpProvidersWithPageResponse>('/admin/mcp', { params })
  return response.data
}
