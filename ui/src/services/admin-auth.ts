import { get, post } from '@/utils/request'
import storage from '@/utils/storage'
import { ADMIN_CREDENTIAL_STORAGE_KEY, clearStoredAdminCredential } from '@/utils/admin-auth'
import { clearStoredCredential } from '@/utils/auth'
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
  if (response.data.user_access_token) {
    useCredentialStore().update({
      access_token: response.data.user_access_token,
      expire_at: response.data.user_expire_at,
    })
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
  useAdminStore().clear()
  return response
}
