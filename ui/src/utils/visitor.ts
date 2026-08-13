const VISITOR_ID_STORAGE_KEY = 'yuxin-ai:visitor-id'

/**
 * 获取当前浏览器稳定的访客 ID，用于匿名 WebApp 会话的工具确认与授权。
 * 已登录用户不依赖该 ID；匿名用户用它把对话流、确认请求绑定到同一主体。
 */
export const getOrCreateVisitorId = (): string => {
  try {
    let visitorId = localStorage.getItem(VISITOR_ID_STORAGE_KEY)
    if (!visitorId) {
      visitorId = crypto.randomUUID()
      localStorage.setItem(VISITOR_ID_STORAGE_KEY, visitorId)
    }
    return visitorId
  } catch {
    return ''
  }
}
