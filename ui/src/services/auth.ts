import { post } from '@/utils/request'
import { getCredentialSessionId, getStoredCredential } from '@/utils/auth'
import { type BaseResponse } from '@/models/base'
import {
  type PasswordLoginResponse,
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
export const prepareRegister = (username: string, email: string, password: string) => {
  return post<PrepareRegisterResponse>(`/auth/register/prepare`, {
    body: { username, email, password },
  })
}

// 直接注册（无需邮箱验证码）
export const directRegister = (username: string, password: string) => {
  return post<PrepareRegisterResponse>(`/auth/register/direct`, {
    body: { username, password },
  })
}

// 校验注册验证码并完成注册
export const verifyRegister = (username: string, email: string, password: string, code: string) => {
  return post<VerifyRegisterResponse>(`/auth/register/verify`, {
    body: { username, email, password, code },
  })
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

// 完成异常登录二次验证
export const verifyLoginChallenge = (challenge_id: string, code: string) => {
  return post<VerifyLoginChallengeResponse>(`/auth/login-challenge/verify`, {
    body: { challenge_id, code },
  })
}

// 重发异常登录验证码
export const resendLoginChallenge = (challenge_id: string) => {
  return post<BaseResponse<Record<string, unknown>>>(`/auth/login-challenge/resend`, {
    body: { challenge_id },
  })
}
