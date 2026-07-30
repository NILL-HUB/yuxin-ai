import { get, post } from '@/utils/request'
import storage from '@/utils/storage'
import { ADMIN_CREDENTIAL_STORAGE_KEY, clearStoredAdminCredential } from '@/utils/admin-auth'
import { CREDENTIAL_STORAGE_KEY, clearStoredCredential } from '@/utils/auth'
import { useAdminStore } from '@/stores/admin'
import { useCredentialStore } from '@/stores/credential'
import { type BaseResponse } from '@/models/base'
import { type AdminLoginResponse, type AdminMeResponse } from '@/models/admin-auth'

export const adminLogin = async (identifier: string, password: string) => {
  const response = await post<AdminLoginResponse>('/admin/auth/login', {
    body: { identifier, password },
  })
  storage.set(ADMIN_CREDENTIAL_STORAGE_KEY, {
    access_token: response.data.admin_access_token || response.data.access_token,
    expire_at: response.data.expire_at,
  })
  // 同时保存用户端凭证，让管理员可调用 /apps、/language-models 等用户端 API
  // 注意：必须同步更新 Pinia credentialStore，因为 request.ts 优先从 store 读取
  const userAccessToken = response.data.user_access_token || response.data.access_token
  const userExpireAt = response.data.user_expire_at || response.data.expire_at
  if (userAccessToken && userExpireAt) {
    const userCredential = {
      access_token: userAccessToken,
      expire_at: userExpireAt,
    }
    storage.set(CREDENTIAL_STORAGE_KEY, userCredential)
    try {
      useCredentialStore().update(userCredential)
    } catch (_error) {
      // Pinia 尚未初始化时（如首屏渲染前），跳过 store 更新，仅写入 storage
    }
  }
  useAdminStore().update(response.data.admin_user)
  return response
}

export const getCurrentAdmin = async () => {
  const response = await get<AdminMeResponse>('/admin/auth/me')
  useAdminStore().update(response.data)
  return response
}

export const adminChangePassword = async (currentPassword: string, newPassword: string) => {
  return await post<AdminMeResponse>('/admin/auth/password', {
    body: { current_password: currentPassword, new_password: newPassword },
  })
}

export const adminLogout = async () => {
  const response = await post<BaseResponse<Record<string, never>>>('/admin/auth/logout')
  clearStoredAdminCredential()
  clearStoredCredential()
  try {
    useCredentialStore().clear()
  } catch (_error) {
    // Pinia 尚未初始化时跳过
  }
  useAdminStore().clear()
  return response
}
