import { get, post, request } from '@/utils/request'
import { type BaseResponse } from '@/models/base'

const patch = <T>(url: string, body?: Record<string, unknown>) =>
  request<T>(url, { method: 'PATCH', body })

export interface AdminUser {
  id: string
  username: string
  email: string
  name: string
  avatar: string
  status: string
  roles: string[]
  is_online: boolean
  account_id?: string | null
  created_at?: number | null
  last_login_at?: number | null
  last_login_ip?: string
}

export type AdminUserPaginator = {
  total_page: number
  total_record: number
  current_page: number
  page_size: number
}

export type AdminUserListData = {
  list: AdminUser[]
  paginator: AdminUserPaginator
}

export type ListAdminUsersParams = {
  search?: string
  status?: string
  current_page?: number
  page_size?: number
}

export type CreateAdminUserPayload = {
  username?: string
  email?: string
  name: string
  password: string
  role_codes?: string[]
}

export type UpdateAdminUserPayload = Partial<{
  name: string
  email: string
  status: string
  role_codes: string[]
}>

export const listAdminUsers = (params?: ListAdminUsersParams) =>
  get<BaseResponse<AdminUserListData>>('/admin/admin-users', { params })

export const createAdminUser = (data: CreateAdminUserPayload) =>
  post<BaseResponse<AdminUser>>('/admin/admin-users', { body: data })

export const getAdminUser = (id: string) =>
  get<BaseResponse<AdminUser>>(`/admin/admin-users/${id}`)

export const updateAdminUser = (id: string, data: UpdateAdminUserPayload) =>
  patch<BaseResponse<AdminUser>>(`/admin/admin-users/${id}`, data)

export const disableAdminUser = (id: string) =>
  post<BaseResponse<Record<string, unknown>>>(`/admin/admin-users/${id}/disable`)

export const enableAdminUser = (id: string) =>
  post<BaseResponse<AdminUser>>(`/admin/admin-users/${id}/enable`)

export const resetAdminUserPassword = (id: string, password: string) =>
  post<BaseResponse<AdminUser>>(`/admin/admin-users/${id}/reset-password`, { body: { password } })

export const revokeAdminUserSessions = (adminId: string) => {
  return post<BaseResponse<{ revoked_sessions: number }>>(`/admin/admin-users/${adminId}/sessions/revoke`)
}
