import { type BaseResponse } from '@/models/base'
import { type AdminProfile } from '@/stores/admin'

export type AdminCredentialData = {
  access_token: string
  expire_at: number
}

export type AdminLoginData = AdminCredentialData & {
  admin_access_token?: string
  admin_user: AdminProfile
}

export type AdminLoginResponse = BaseResponse<AdminLoginData>

export type AdminMeResponse = BaseResponse<AdminProfile>
