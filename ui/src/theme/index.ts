import { computed, ref, watchEffect } from 'vue'
import storage from '@/utils/storage'

/**
 * 模块化主题系统
 *
 * 设计目标：多套主题一键切换，新主题只需：
 *   1. 在 theme.css 增加一个 [data-theme="xxx"] token 块
 *   2. 在此处注册 themeId 与展示名
 * 即可接入切换 UI，无需改动任何组件。
 *
 * 切换机制（三层 token 并联，单一切换开关）：
 *   - document.documentElement.setAttribute('data-theme', themeId)
 *       → 驱动 theme.css 中的 --tw-* / --aicss-* 变量
 *   - document.body.setAttribute('arco-theme', themeId === 'barbie-dark' ? 'dark' : 'light')
 *       → 驱动 Arco Design Vue 的暗色/亮色变量
 *   - 持久化到 localStorage
 */

export type ThemeId = 'barbie' | 'barbie-dark'

export interface ThemeOption {
  id: ThemeId
  label: string
}

export const THEME_OPTIONS: ThemeOption[] = [
  { id: 'barbie', label: '芭比粉' },
  { id: 'barbie-dark', label: '芭比暗夜' },
]

const THEME_STORAGE_KEY = 'yuxin-theme'

function isThemeId(value: unknown): value is ThemeId {
  return typeof value === 'string' && THEME_OPTIONS.some((option) => option.id === value)
}

function getInitialTheme(): ThemeId {
  const stored = storage.get<string | null>(THEME_STORAGE_KEY, null)
  if (isThemeId(stored)) return stored
  return 'barbie'
}

const themeId = ref<ThemeId>(getInitialTheme())

/** 当前主题 id */
export function useThemeId() {
  return computed(() => themeId.value)
}

/** 当前主题是否为暗色（驱动 Arco 属性） */
export function useIsDarkTheme() {
  return computed(() => themeId.value === 'barbie-dark')
}

/** 切换主题并持久化 */
export function setTheme(next: ThemeId) {
  if (!isThemeId(next)) return
  themeId.value = next
  storage.set(THEME_STORAGE_KEY, next)
}

/** 切换主题（便捷方法，供切换按钮使用） */
export function toggleTheme() {
  setTheme(themeId.value === 'barbie' ? 'barbie-dark' : 'barbie')
}

/** 应用主题到 DOM（需在组件挂载后调用，或在 useTheme 中 watchEffect） */
export function applyThemeToDom() {
  if (typeof document === 'undefined') return
  document.documentElement.setAttribute('data-theme', themeId.value)
  document.body.setAttribute('arco-theme', themeId.value === 'barbie-dark' ? 'dark' : 'light')
  document.documentElement.style.colorScheme = themeId.value === 'barbie-dark' ? 'dark' : 'light'
}

/** 组合式入口：挂载时应用主题并响应切换 */
export function useTheme() {
  watchEffect(() => {
    applyThemeToDom()
  })
  return {
    themeId,
    isDark: useIsDarkTheme(),
    options: THEME_OPTIONS,
    setTheme,
    toggleTheme,
  }
}
