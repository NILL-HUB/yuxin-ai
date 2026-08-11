import { get } from '@/utils/request'
import type { BaseResponse } from '@/models/base'
import type {
  AdminRoutingLogFilters,
  AdminRoutingLogListResponse,
} from '@/models/admin-routing-log'

export const listAdminRoutingLogs = async (
  params: AdminRoutingLogFilters,
): Promise<AdminRoutingLogListResponse> => {
  const response = await get<BaseResponse<AdminRoutingLogListResponse>>(
    '/admin/routing-logs',
    { params },
  )
  return response.data
}
