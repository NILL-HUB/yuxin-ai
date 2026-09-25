/**
 * 管理端 Agent 治理域的共享展示工具。
 *
 * 背景：Agent 池配置 / 子池定义 / 管理端 Agent 列表三处都需要「确定性渐变头像」
 * 与统一的时间格式化。此前各页各自实现或缺失，导致视觉不一致；此处收敛为单一实现。
 */

/** 渐变头像调色板（深色系，与 admin 侧边栏气质一致）。 */
export const AGENT_AVATAR_PALETTES: ReadonlyArray<readonly [string, string]> = [
  ['#334155', '#0f172a'],
  ['#0369a1', '#1d4ed8'],
  ['#047857', '#0f766e'],
  ['#c2410c', '#d97706'],
  ['#be123c', '#e11d48'],
  ['#0f766e', '#14b8a6'],
  ['#7c3aed', '#a855f7'],
  ['#b45309', '#f59e0b'],
]

/**
 * 稳定字符串哈希（djb2 变体，32 位无符号）。
 * 同一 seed 恒返回同一值，保证头像颜色在刷新/重排后不变。
 */
export const hashString = (value: string): number => {
  let hash = 0
  const text = String(value ?? '')
  for (let i = 0; i < text.length; i += 1) {
    hash = (hash * 33 + text.charCodeAt(i)) >>> 0
  }
  return hash
}

/**
 * 从名称中提炼 1~2 个字符作为头像文字。
 * 拉丁字符优先取词首字母（最多 2 个），中文取前 2 字，其他回退前 2 字符。
 */
export const extractAvatarText = (source: string): string => {
  const text = String(source ?? '').trim()
  if (!text) return '?'

  const latinParts = text.match(/[A-Za-z0-9]+/g)
  if (latinParts && latinParts.length > 0) {
    return latinParts
      .slice(0, 2)
      .map((part) => part[0]?.toUpperCase() ?? '')
      .join('')
  }

  const chineseParts = text.match(/[\u4e00-\u9fff]/g)
  if (chineseParts && chineseParts.length > 0) {
    return chineseParts.slice(0, 2).join('')
  }

  return text.slice(0, 2).toUpperCase()
}

/**
 * 由 seed 生成确定性渐变头像样式。
 * 返回内联样式对象，可直接绑定到元素 :style。
 */
export const getAgentAvatarStyle = (seed: string) => {
  const palette = AGENT_AVATAR_PALETTES[hashString(seed) % AGENT_AVATAR_PALETTES.length]
  return {
    background: `linear-gradient(135deg, ${palette[0]} 0%, ${palette[1]} 100%)`,
    boxShadow: 'inset 0 1px 0 rgba(255, 255, 255, 0.15)',
  }
}

/** 由名称直接取头像文字（常用组合，避免调用方重复写 extract）。 */
export const getAgentAvatarText = (name: string): string => extractAvatarText(name)

/**
 * 秒级时间戳格式化为本地时间字符串。
 * 空值返回占位符，避免渲染出 NaN/Invalid Date。
 */
export const formatAgentTime = (value: number | null | undefined, placeholder = '-'): string => {
  if (!value) return placeholder
  return new Date(value * 1000).toLocaleString('zh-CN', { hour12: false })
}
