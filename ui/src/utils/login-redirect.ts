import router from '@/router'
import auth from '@/utils/auth'

const LOGIN_PATH = '/auth/login'

const isLoginPath = (path: string): boolean => {
  return path === LOGIN_PATH || path.startsWith(`${LOGIN_PATH}?`)
}

const isSafeInternalRedirect = (target: string): boolean => {
  // 仅允许站内路径：以单 / 开头、不以 // 或 /auth/login 自身开头（防开放重定向与循环）
  if (!target || !target.startsWith('/')) return false
  if (target.startsWith('//')) return false
  if (isLoginPath(target.split('?')[0])) return false
  return true
}

/**
 * 统一跳转登录页并携带回跳地址。
 * 已在登录页时不动作；已登录时不动作。
 */
export const redirectToLogin = (): void => {
  const current = router.currentRoute.value
  if (current.path.startsWith('/admin')) return
  if (auth.isLogin()) return
  const currentFullPath = current.fullPath
  if (isLoginPath(currentFullPath.split('?')[0])) return
  const query: Record<string, string> = {}
  if (currentFullPath && currentFullPath !== '/') {
    query.redirect = currentFullPath
  }
  void router.push({ path: LOGIN_PATH, query })
}

/**
 * 构造登录页跳转目标（供手动 push 时使用）。
 */
export const buildLoginLocation = (redirectPath = ''): { path: string; query: Record<string, string> } => {
  const query: Record<string, string> = {}
  if (redirectPath && isSafeInternalRedirect(redirectPath)) {
    query.redirect = redirectPath
  }
  return { path: LOGIN_PATH, query }
}

/**
 * 解析登录成功后的回跳地址；不合法则回落到默认路径。
 */
export const resolveLoginRedirect = (redirectPath: string | null | undefined, fallback = '/home'): string => {
  if (redirectPath && isSafeInternalRedirect(redirectPath)) {
    return redirectPath
  }
  return fallback
}

export { isSafeInternalRedirect }
