import { post } from '@/utils/request'
import { type BaseResponse } from '@/models/base'

// 发送绑定手机号验证码
export const sendBindPhoneCode = (phone: string) => {
  return post<BaseResponse<Record<string, unknown>>>(`/account/security/send-bind-phone-code`, {
    body: { phone },
  })
}

// 绑定手机号
export const bindPhone = (phone: string, code: string) => {
  return post<BaseResponse<Record<string, unknown>>>(`/account/security/bind-phone`, {
    body: { phone, code },
  })
}

// 解绑手机号
export const unbindPhone = (code: string) => {
  return post<BaseResponse<Record<string, unknown>>>(`/account/security/unbind-phone`, {
    body: { code },
  })
}

// 发送验证邮箱验证码
export const sendVerifyEmailCode = () => {
  return post<BaseResponse<Record<string, unknown>>>(`/account/security/send-verify-email-code`)
}

// 验证邮箱
export const verifyEmail = (code: string) => {
  return post<BaseResponse<Record<string, unknown>>>(`/account/security/verify-email`, {
    body: { code },
  })
}
