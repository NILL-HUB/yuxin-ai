import { get } from '@/utils/request'
import type {
  AdminRoutingLogFilters,
  AdminRoutingLogListResponse,
} from '@/models/admin-routing-log'

export const listAdminRoutingLogs = (params: AdminRoutingLogFilters) => {
  return get<AdminRoutingLogListResponse>('/admin/routing-logs', { params })
}
