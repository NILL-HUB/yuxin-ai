import { get, post, del, request } from '@/utils/request'
import { type BaseResponse } from '@/models/base'

const patch = <T>(url: string, body?: Record<string, unknown>) =>
  request<T>(url, { method: 'PATCH', body })

export interface Role {
  code: string
  name: string
  description: string
  is_system: boolean
  permissions: string[]
}

export interface Permission {
  code: string
  name: string
  resource: string
  action: string
  description?: string
}

export type CreateRolePayload = {
  code: string
  name: string
  description?: string
  permission_codes?: string[]
}

export type UpdateRolePayload = Partial<{
  name: string
  description: string
  permission_codes: string[]
}>

export const listRoles = () => get<BaseResponse<Role[]>>('/admin/roles')

export const createRole = (data: CreateRolePayload) =>
  post<BaseResponse<Role>>('/admin/roles', { body: data })

export const getRole = (code: string) => get<BaseResponse<Role>>(`/admin/roles/${code}`)

export const updateRole = (code: string, data: UpdateRolePayload) =>
  patch<BaseResponse<Role>>(`/admin/roles/${code}`, data)

export const deleteRole = (code: string) =>
  del<BaseResponse<Record<string, unknown>>>(`/admin/roles/${code}`)

export const listPermissions = () => get<BaseResponse<Permission[]>>('/admin/permissions')
