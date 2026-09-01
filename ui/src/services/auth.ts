import { get, post } from '@/utils/request'
import { getCredentialSessionId, getStoredCredential } from '@/utils/auth'
import { type BaseResponse } from '@/models/base'
import {
  type LoginAuthorizationData,
  type LoginMethodsResponse,
  type PasswordLoginResponse,
  type RegisterInviteInfoResponse,
  type SendCodePayload,
  type VerifyLoginChallengeResponse,
  type PrepareRegisterResponse,
  type VerifyRegisterResponse,
} from '@/models/auth'

// 账号密码登录请求
export const passwordLogin = (identifier: string, password: string) => {
  return post<PasswordLoginResponse>(`/auth/password-login`, {
    body: { identifier, password },
  })
}

// 发送注册验证码
export const prepareRegister = (username: string, email: string, password: string, inviteCode = '') => {
  const body: Record<string, string> = { username, email, password }
  if (inviteCode.trim()) body.invite_code = inviteCode.trim()
  return post<PrepareRegisterResponse>(`/auth/register/prepare`, { body })
}

// 直接注册（无需邮箱验证码）
export const directRegister = (username: string, password: string, inviteCode = '') => {
  const body: Record<string, string> = { username, password }
  if (inviteCode.trim()) body.invite_code = inviteCode.trim()
  return post<PrepareRegisterResponse>(`/auth/register/direct`, { body })
}

// 校验注册验证码并完成注册
export const verifyRegister = (username: string, email: string, password: string, code: string, inviteCode = '') => {
  const body: Record<string, string> = { username, email, password, code }
  if (inviteCode.trim()) body.invite_code = inviteCode.trim()
  return post<VerifyRegisterResponse>(`/auth/register/verify`, { body })
}

// 查询邀请码注册信息（有效性/必填性/邀请人）
export const getRegisterInviteInfo = (code: string) => {
  return get<RegisterInviteInfoResponse>(`/auth/register/invite-info`, { params: { code } })
}

// 退出登录请求
export const logout = () => {
  const session_id = getCredentialSessionId(getStoredCredential())
  if (!session_id) {
    return post<BaseResponse<Record<string, unknown>>>(`/auth/logout`)
  }
  return post<BaseResponse<Record<string, unknown>>>(`/auth/logout`, {
    params: { session_id },
  })
}

// 发送密码重置验证码
export const sendResetCode = (email: string) => {
  return post<BaseResponse<Record<string, unknown>>>(`/auth/send-reset-code`, {
    body: { email },
  })
}

// 重置密码
export const resetPassword = (email: string, code: string, new_password: string) => {
  return post<BaseResponse<Record<string, unknown>>>(`/auth/reset-password`, {
    body: { email, code, new_password },
  })
}

// 获取当前启用的登录方式开关
export const getLoginMethods = () => {
  return get<LoginMethodsResponse>(`/auth/login-methods`)
}

// 统一验证码发送入口（邮箱/手机号通道）
export const sendCode = (payload: SendCodePayload) => {
  return post<BaseResponse<Record<string, unknown>>>(`/auth/send-code`, {
    body: payload,
  })
}

// 手机号验证码登录
export const phoneCodeLogin = (phone: string, code: string) => {
  return post<PasswordLoginResponse>(`/auth/phone-code-login`, {
    body: { phone, code },
  })
}

// 邮箱验证码登录
export const emailCodeLogin = (email: string, code: string) => {
  return post<PasswordLoginResponse>(`/auth/email-code-login`, {
    body: { email, code },
  })
}

// 手机号注册：发送注册验证码
export const phoneRegisterRequest = (phone: string) => {
  return post<BaseResponse<Record<string, unknown>>>(`/auth/register/phone-prepare`, {
    body: { phone },
  })
}

// 手机号注册：校验验证码并完成注册
export const phoneRegisterVerify = (
  phone: string,
  code: string,
  options: { username?: string; password?: string } = {},
) => {
  const body: Record<string, string> = { phone, code }
  if (options.username?.trim()) body.username = options.username.trim()
  if (options.password) body.password = options.password
  return post<VerifyRegisterResponse>(`/auth/register/phone-verify`, { body })
}

// 完成异常登录二次验证
export const verifyLoginChallenge = (challenge_id: string, code: string, channel = '') => {
  const body: Record<string, string> = { challenge_id, code }
  if (channel) body.channel = channel
  return post<VerifyLoginChallengeResponse>(`/auth/login-challenge/verify`, {
    body,
  })
}

// 重发异常登录验证码
export const resendLoginChallenge = (challenge_id: string, channel = '') => {
  const body: Record<string, string> = { challenge_id }
  if (channel) body.channel = channel
  return post<BaseResponse<Record<string, unknown>>>(`/auth/login-challenge/resend`, {
    body,
  })
}
