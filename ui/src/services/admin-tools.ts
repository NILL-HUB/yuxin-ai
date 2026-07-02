import { get } from '@/utils/request'
import type { AdminToolsPageData, GetAdminToolsParams } from '@/models/admin-tool'

/**
 * 获取后台 API 工具治理入口分页数据。
 */
export const listAdminTools = (params: GetAdminToolsParams) => {
  return get<AdminToolsPageData>('/admin/tools', { params })
}
