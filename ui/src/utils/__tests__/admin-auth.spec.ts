import { afterEach, describe, expect, it } from 'vitest'
import storage from '@/utils/storage'
import {
  ADMIN_CREDENTIAL_STORAGE_KEY,
  clearStoredAdminCredential,
  getAdminCredentialAccessToken,
  getStoredAdminCredential,
  isAdminCredentialLoggedIn,
} from '@/utils/admin-auth'

describe('admin auth utils', () => {
  afterEach(() => {
    localStorage.clear()
  })

  it('uses an admin-specific storage key separated from customer credentials', () => {
    expect(ADMIN_CREDENTIAL_STORAGE_KEY).toBe('admin_credential')

    storage.set('credential', { access_token: 'customer-token', expire_at: Math.floor(Date.now() / 1000) + 3600 })
    storage.set('admin_credential', { access_token: 'admin-token', expire_at: Math.floor(Date.now() / 1000) + 3600 })

    expect(getStoredAdminCredential()?.access_token).toBe('admin-token')
    clearStoredAdminCredential()
    expect(storage.get('credential').access_token).toBe('customer-token')
    expect(storage.get('admin_credential')).toBe('')
  })

  it('returns empty token and logged-out state when admin credential is missing or expired', () => {
    expect(getAdminCredentialAccessToken()).toBe('')
    expect(isAdminCredentialLoggedIn()).toBe(false)
    expect(
      getAdminCredentialAccessToken({
        access_token: 'expired-admin-token',
        expire_at: Math.floor(Date.now() / 1000) - 60,
      }),
    ).toBe('')
    expect(
      isAdminCredentialLoggedIn({
        access_token: 'expired-admin-token',
        expire_at: Math.floor(Date.now() / 1000) - 60,
      }),
    ).toBe(false)
  })

  it('returns admin token and logged-in state when admin credential is valid', () => {
    const credential = {
      access_token: 'admin-token',
      expire_at: Math.floor(Date.now() / 1000) + 3600,
    }

    expect(getAdminCredentialAccessToken(credential)).toBe('admin-token')
    expect(isAdminCredentialLoggedIn(credential)).toBe(true)
  })
})
