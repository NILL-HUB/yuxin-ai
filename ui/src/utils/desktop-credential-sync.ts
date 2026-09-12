import { CREDENTIAL_STORAGE_KEY } from '@/utils/auth'
import storage from '@/utils/storage'
import type { CredentialLike } from '@/utils/auth'

type DesktopCredentialBridge = {
  getCredential: () => Promise<string | null>
  setCredential: (token: string) => Promise<unknown>
  clearCredential: () => Promise<unknown>
  registerDevice?: () => Promise<unknown>
}

const resolveDesktopBridge = (): DesktopCredentialBridge | null => {
  if (typeof window === 'undefined') return null
  const bridge = (window as unknown as { yujianwoDesktop?: DesktopCredentialBridge }).yujianwoDesktop
  if (!bridge?.getCredential || !bridge?.setCredential || !bridge?.clearCredential) return null
  return bridge
}

// localStorage 内没有本地凭证（access_token 为空），但主进程 safeStorage 存有 token 时回填。
// 回填直接写 localStorage，不走 store.update，避免把过期语义不完整的 token 再次同步回主进程造成幂等回环。
export const restoreCredentialFromDesktop = async (): Promise<void> => {
  const bridge = resolveDesktopBridge()
  if (!bridge) return

  const current = storage.get(CREDENTIAL_STORAGE_KEY, null) as CredentialLike | null
  const currentToken = String(current?.access_token || '').trim()
  if (currentToken) return

  let token: string | null = null
  try {
    token = await bridge.getCredential()
  } catch {
    return
  }
  const accessToken = String(token || '').trim()
  if (!accessToken) return

  const expireAt = Number(current?.expire_at || 0)
  storage.set(CREDENTIAL_STORAGE_KEY, {
    access_token: accessToken,
    expire_at: expireAt > 0 ? expireAt : Math.floor(Date.now() / 1000) + 365 * 24 * 60 * 60,
  })
}

export const syncCredentialToDesktop = (credential: CredentialLike | null): Promise<unknown> => {
  const bridge = resolveDesktopBridge()
  if (!bridge) return Promise.resolve()

  const accessToken = String(credential?.access_token || '').trim()
  if (!accessToken) {
    return bridge.clearCredential().catch(() => undefined)
  }
  // 登录成功即注册本机设备：setCredential 落盘后主动触发一次设备注册，
  // 使服务端能按账号动态解析本机 bridge（避免启动时无凭证导致漏注册）。
  return bridge
    .setCredential(accessToken)
    .then(() => (bridge.registerDevice ? bridge.registerDevice() : undefined))
    .catch(() => undefined)
}
