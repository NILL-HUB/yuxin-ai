import { get, patch, post, put } from '@/utils/request'
import {
  type CustomerUserDetailResponse,
  type CustomerUserListRequest,
  type CustomerUserListResponse,
  type CustomerUserResponse,
  type RevokeCustomerUserSessionsResponse,
  type SetCustomerUserSuperiorResponse,
} from '@/models/admin-customer-user'

export const listCustomerUsers = async (params: CustomerUserListRequest) => {
  const response = await get<CustomerUserListResponse>('/admin/users', { params })
  return response.data
}

export const getCustomerUser = async (id: string) => {
  const response = await get<CustomerUserDetailResponse>(`/admin/users/${id}`)
  return response.data
}

export const disableCustomerUser = async (id: string, reason: string) => {
  const response = await post<CustomerUserResponse>(`/admin/users/${id}/disable`, { body: { reason } })
  return response.data
}

export const createCustomerUser = async (payload: {
  email: string
  name: string
  password?: string
  username?: string
  phone?: string
}) => {
  const response = await post<CustomerUserResponse>('/admin/users', { body: payload })
  return response.data
}

export const updateCustomerUser = async (
  id: string,
  payload: { name?: string; email?: string; phone?: string; password?: string },
) => {
  const response = await patch<CustomerUserResponse>(`/admin/users/${id}`, { body: payload })
  return response.data
}

export const deleteCustomerUser = async (id: string, reason: string) => {
  const response = await post<CustomerUserResponse>(`/admin/users/${id}/delete`, { body: { reason } })
  return response.data
}

export const enableCustomerUser = async (id: string) => {
  const response = await post<CustomerUserResponse>(`/admin/users/${id}/enable`)
  return response.data
}

export const revokeCustomerUserSessions = async (id: string) => {
  const response = await post<RevokeCustomerUserSessionsResponse>(`/admin/users/${id}/sessions/revoke`)
  return response.data
}

export const setCustomerUserSuperior = async (id: string, inviterId: string | null) => {
  const response = await put<SetCustomerUserSuperiorResponse>(`/admin/users/${id}/superior`, {
    body: { inviter_id: inviterId },
  })
  return response.data
}
