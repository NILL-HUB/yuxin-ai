import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { CREDENTIAL_STORAGE_KEY } from '@/utils/auth'
import { restoreCredentialFromDesktop, syncCredentialToDesktop } from '@/utils/desktop-credential-sync'
import storage from '@/utils/storage'

const bridge = {
  getCredential: vi.fn().mockResolvedValue('desktop-token'),
  setCredential: vi.fn().mockResolvedValue(undefined),
  clearCredential: vi.fn().mockResolvedValue(undefined),
}

describe('desktop credential sync', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    localStorage.clear()
    Object.defineProperty(window, 'yujianwoDesktop', { value: bridge, configurable: true })
  })

  afterEach(() => {
    Object.defineProperty(window, 'yujianwoDesktop', { value: undefined, configurable: true })
  })

  it('does nothing in web runtime without yujianwoDesktop', async () => {
    Object.defineProperty(window, 'yujianwoDesktop', { value: undefined, configurable: true })

    storage.set(CREDENTIAL_STORAGE_KEY, { access_token: 'web-token', expire_at: 0 })
    await restoreCredentialFromDesktop()
    expect(bridge.getCredential).not.toHaveBeenCalled()

    await syncCredentialToDesktop({ access_token: 'web-token', expire_at: 0 })
    expect(bridge.setCredential).not.toHaveBeenCalled()
  })

  it('skips restore when local credential already exists', async () => {
    storage.set(CREDENTIAL_STORAGE_KEY, { access_token: 'local-token', expire_at: 0 })

    await restoreCredentialFromDesktop()

    expect(bridge.getCredential).not.toHaveBeenCalled()
    expect(storage.get(CREDENTIAL_STORAGE_KEY, null)?.access_token).toBe('local-token')
  })

  it('restores token from desktop bridge and treats it as long-lived', async () => {
    await restoreCredentialFromDesktop()

    const credential = storage.get(CREDENTIAL_STORAGE_KEY, null)
    expect(credential.access_token).toBe('desktop-token')
    expect(credential.expire_at).toBeGreaterThan(Math.floor(Date.now() / 1000))
  })

  it('keeps local expire_at when restoring an expired-flagged credential', async () => {
    storage.set(CREDENTIAL_STORAGE_KEY, { access_token: '', expire_at: 0 })
    bridge.getCredential.mockResolvedValueOnce('desktop-token')

    await restoreCredentialFromDesktop()

    const credential = storage.get(CREDENTIAL_STORAGE_KEY, null)
    expect(credential.access_token).toBe('desktop-token')
    expect(credential.expire_at).toBeGreaterThan(Math.floor(Date.now() / 1000))
  })

  it('does not restore when the desktop has no stored token', async () => {
    bridge.getCredential.mockResolvedValueOnce(null)

    await restoreCredentialFromDesktop()

    expect(storage.get(CREDENTIAL_STORAGE_KEY, null)).toBeNull()
  })

  it('sets credential in the desktop bridge on update', async () => {
    await syncCredentialToDesktop({ access_token: 'new-token', expire_at: 0 })

    expect(bridge.setCredential).toHaveBeenCalledWith('new-token')
    expect(bridge.clearCredential).not.toHaveBeenCalled()
  })

  it('clears the desktop bridge when credential is emptied', async () => {
    await syncCredentialToDesktop({ access_token: '', expire_at: 0 })

    expect(bridge.clearCredential).toHaveBeenCalled()
    expect(bridge.setCredential).not.toHaveBeenCalled()
  })
})
