import { get } from '@/utils/request'
import { type BaseResponse } from '@/models/base'

export interface AuditLog {
  id: string
  admin_user_id?: string
  admin_user_name?: string
  account_id?: string
  account_name?: string
  action: string
  resource_type?: string
  resource_id?: string
  ip?: string
  user_agent?: string
  before_data?: Record<string, unknown>
  after_data?: Record<string, unknown>
  created_at: number
}

export type AuditLogPaginator = {
  total_page: number
  total_record: number
  current_page: number
  page_size: number
}

export type AuditLogListData = {
  list: AuditLog[]
  paginator: AuditLogPaginator
}

export type ListAuditLogsParams = {
  action?: string
  resource_type?: string
  admin_user_id?: string
  start_time?: number
  end_time?: number
  current_page?: number
  page_size?: number
}

export const listAuditLogs = (params?: ListAuditLogsParams) =>
  get<BaseResponse<AuditLogListData>>('/admin/audit-logs', { params })
