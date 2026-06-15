import storage from '@/utils/storage'
import { getCredentialAccessToken, isCredentialLoggedIn, type CredentialLike } from '@/utils/auth'

export const ADMIN_CREDENTIAL_STORAGE_KEY = 'admin_credential'

export type AdminCredentialLike = CredentialLike

export const getAdminCredentialAccessToken = (credential?: AdminCredentialLike | null): string => {
  return getCredentialAccessToken(credential)
}

export const isAdminCredentialLoggedIn = (credential?: AdminCredentialLike | null): boolean => {
  return isCredentialLoggedIn(credential)
}

export const getStoredAdminCredential = (): AdminCredentialLike | null => {
  return storage.get(ADMIN_CREDENTIAL_STORAGE_KEY, null) as AdminCredentialLike | null
}

export const clearStoredAdminCredential = (): void => {
  storage.remove(ADMIN_CREDENTIAL_STORAGE_KEY)
}
