import { type BaseResponse } from '@/models/base'
import { type AdminProfile } from '@/stores/admin'

export type AdminLoginUser = {
  id: string
  username: string
  email: string
  name: string
  avatar: string
  status: string
}

export type AdminCredentialData = {
  access_token: string
  expire_at: number
}

export type AdminLoginData = AdminCredentialData & {
  admin_access_token?: string
  user_access_token?: string
  user_expire_at?: number
  admin_user: AdminProfile
  user?: AdminLoginUser
}

export type AdminLoginResponse = BaseResponse<AdminLoginData>

export type AdminMeResponse = BaseResponse<AdminProfile>
