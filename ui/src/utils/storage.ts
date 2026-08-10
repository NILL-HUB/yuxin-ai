export default {
  // 获取localStorage中的值
  get: <T>(key: string, defaultValue: T): T => {
    const value = localStorage.getItem(key)
    if (value) {
      try {
        return JSON.parse(value) as T
      } catch {
        return value as T
      }
    }
    return defaultValue
  },
  // 设置localStorage中的值
  set: (key: string, value: unknown): void => {
    if (typeof value === 'string') {
      localStorage.setItem(key, value)
    } else {
      localStorage.setItem(key, JSON.stringify(value))
    }
  },
  // 移除localStorage中的值
  remove: (key: string): void => {
    localStorage.removeItem(key)
  },
  // 清除localStorage中的所有值
  clear: (): void => {
    localStorage.clear()
  },
}
