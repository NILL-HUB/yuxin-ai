import { type BaseResponse } from '@/models/base'

export type RegisterInviteInfo = {
  valid: boolean
  required: boolean
  inviter_name: string
}

export type RegisterInviteInfoResponse = BaseResponse<RegisterInviteInfo>

export type LoginChallengeChannel = {
  type: 'email' | 'phone'
  masked?: string
  email?: string
  phone?: string
}

export type LoginAuthorizationData = {
  access_token?: string
  expire_at?: number
  challenge_required?: boolean
  challenge_id?: string
  challenge_type?: string
  masked_email?: string
  channels?: LoginChallengeChannel[]
  risk_reason?: string
}

// 登录方式开关响应结构
export type LoginMethodsResponse = BaseResponse<{
  email_enabled: boolean
  phone_enabled: boolean
  challenge_enabled: boolean
}>

// 统一验证码发送请求参数
export type SendCodePayload = {
  scene: string
  email?: string
  phone?: string
  challenge_id?: string
  channel?: string
}

// 账号密码登录响应结构
export type PasswordLoginResponse = BaseResponse<LoginAuthorizationData>

export type PrepareRegisterResponse = BaseResponse<Record<string, never>>

export type VerifyRegisterResponse = BaseResponse<LoginAuthorizationData>

export type VerifyLoginChallengeResponse = BaseResponse<LoginAuthorizationData>
