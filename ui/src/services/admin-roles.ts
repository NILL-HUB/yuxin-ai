import { get, post, del, request } from '@/utils/request'
import { type BaseResponse } from '@/models/base'

const patch = <T>(url: string, body?: Record<string, unknown>) =>
  request<T>(url, { method: 'PATCH', body })

export interface Role {
  id: string
  code: string
  name: string
  description: string
  is_system: boolean
  permissions: string[]
}

export interface Permission {
  id: string
  code: string
  name: string
  resource: string
  action: string
}

export type CreateRolePayload = {
  code: string
  name: string
  description?: string
  permission_ids?: string[]
}

export type UpdateRolePayload = Partial<{
  name: string
  description: string
  permission_ids: string[]
}>

export const listRoles = () => get<BaseResponse<Role[]>>('/admin/roles')

export const createRole = (data: CreateRolePayload) =>
  post<BaseResponse<Role>>('/admin/roles', { body: data })

export const getRole = (id: string) => get<BaseResponse<Role>>(`/admin/roles/${id}`)

export const updateRole = (id: string, data: UpdateRolePayload) =>
  patch<BaseResponse<Role>>(`/admin/roles/${id}`, data)

export const deleteRole = (id: string) =>
  del<BaseResponse<Record<string, unknown>>>(`/admin/roles/${id}`)

export const listPermissions = () => get<BaseResponse<Permission[]>>('/admin/permissions')
