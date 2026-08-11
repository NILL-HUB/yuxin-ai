import { get, post } from '@/utils/request'
import { getCredentialSessionId, getStoredCredential } from '@/utils/auth'
import { type BaseResponse } from '@/models/base'
import {
  type GetAccountLoginHistoryResponse,
  type GetAccountSessionsResponse,
  type GetCurrentUserResponse,
} from '@/models/account'

const getCurrentSessionId = () => getCredentialSessionId(getStoredCredential())

// 获取当前登录账号信息
export const getCurrentUser = () => {
  return get<GetCurrentUserResponse>(`/account`)
}

// 修改当前登录账号密码
export const updatePassword = (current_password: string, new_password: string) => {
  return post<BaseResponse<Record<string, unknown>>>(`/account/password`, {
    body: { current_password, new_password },
  })
}

// 修改当前登录账号名称
export const updateName = (name: string) => {
  return post<BaseResponse<Record<string, unknown>>>(`/account/name`, {
    body: { name },
  })
}

// 修改当前登录账号头像
export const updateAvatar = (avatar: string) => {
  return post<BaseResponse<Record<string, unknown>>>(`/account/avatar`, {
    body: { avatar },
  })
}

// 发送换绑邮箱验证码
export const sendChangeEmailCode = (email: string) => {
  return post<BaseResponse<Record<string, unknown>>>(`/account/email/send-code`, {
    body: { email },
  })
}

// 更新当前登录账号邮箱
export const updateEmail = (email: string, code: string, current_password: string = '') => {
  return post<BaseResponse<Record<string, unknown>>>(`/account/email`, {
    body: { email, code, current_password },
  })
}

// 获取当前账号的登录会话
export const getAccountSessions = () => {
  const session_id = getCurrentSessionId()
  if (!session_id) {
    return get<GetAccountSessionsResponse>(`/account/sessions`)
  }
  return get<GetAccountSessionsResponse>(`/account/sessions`, {
    params: { session_id },
  })
}

// 获取当前账号最近的登录历史
export const getAccountLoginHistory = (params?: {
  status?: string
  search?: string
  current_page?: number
  page_size?: number
}) => {
  const session_id = getCurrentSessionId()
  return get<GetAccountLoginHistoryResponse>(`/account/login-history`, {
    params:
      params || session_id
        ? {
            ...params,
            ...(session_id ? { session_id } : {}),
          }
        : undefined,
  })
}

// 下线指定登录会话
export const revokeAccountSession = (session_id: string) => {
  const current_session_id = getCurrentSessionId()
  if (!current_session_id) {
    return post<BaseResponse<Record<string, unknown>>>(`/account/sessions/${session_id}/revoke`)
  }
  return post<BaseResponse<Record<string, unknown>>>(
    `/account/sessions/${session_id}/revoke`,
    { params: { session_id: current_session_id } },
  )
}

// 下线除当前设备外的其他会话
export const revokeOtherAccountSessions = () => {
  const session_id = getCurrentSessionId()
  if (!session_id) {
    return post<BaseResponse<Record<string, unknown>>>(`/account/sessions/revoke-others`)
  }
  return post<BaseResponse<Record<string, unknown>>>(`/account/sessions/revoke-others`, {
    params: { session_id },
  })
}

// 解绑当前第三方账号
export const unbindOAuth = (provider_name: string) => {
  return post<BaseResponse<Record<string, unknown>>>(`/account/oauth/${provider_name}/unbind`)
}
