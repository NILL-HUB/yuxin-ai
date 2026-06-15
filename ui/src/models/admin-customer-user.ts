import { type BasePaginatorResponse, type BaseResponse } from '@/models/base'

export type CustomerUserStatus = 'active' | 'disabled'

export type CustomerUser = {
  id: string
  email: string
  name: string
  avatar: string
  status: CustomerUserStatus
  disabled_at: number | null
  disabled_by: string | null
  disabled_reason: string
  last_login_at: number | null
  last_login_ip: string
  created_at: number | null
}

export type CustomerUserSession = {
  id: string
  status: 'active' | 'revoked'
  user_agent: string
  ip: string
  created_at: number | null
  last_active_at: number | null
  expires_at: number | null
  revoked_at: number | null
}

export type CustomerUserDetail = CustomerUser & {
  sessions: CustomerUserSession[]
}

export type CustomerUserListRequest = {
  keyword?: string
  status?: '' | CustomerUserStatus
  current_page: number
  page_size: number
}

export type CustomerUserListResponse = BasePaginatorResponse<CustomerUser>
export type CustomerUserResponse = BaseResponse<CustomerUser>
export type CustomerUserDetailResponse = BaseResponse<CustomerUserDetail>
export type RevokeCustomerUserSessionsResponse = BaseResponse<{ revoked_sessions: number }>
