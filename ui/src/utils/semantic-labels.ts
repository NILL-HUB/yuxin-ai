/**
 * 语义化标签工具：把观测/日志/记录类页面中暴露的技术枚举值
 * 翻译为高可读语义文本。
 *
 * 字典源：i18n messages（zh-CN/en-US 的 `semantic` 命名空间），
 * 随系统语言自动切换，避免硬编码。
 *
 * 两种展示模式：
 * - semanticLabel(key, value)   → 语义文本（直接展示）
 * - semanticHint(key, value)    → 英文原值（用于悬停浮窗 / tooltip）
 *
 * 用法：
 *   {{ semanticLabel('execution_mode', log.routing_decision?.execution_mode) }}
 *   <a-tooltip :content="semanticHint('execution_mode', value)">...</a-tooltip>
 */

import { i18n } from '@/i18n'

// i18n semantic 命名空间下的分组 key → semantic-labels 使用的逻辑 key
const CATEGORY_KEY_MAP: Record<string, string> = {
  execution_mode: 'executionMode',
  intent: 'intent',
  complexity: 'complexity',
  risk_level: 'riskLevel',
  model_tier: 'modelTier',
  invoke_from: 'invokeFrom',
  routing_status: 'routingStatus',
  resource_type: 'resourceType',
  action: 'action',
  deleted_by_type: 'deletedByType',
  recycle_status: 'recycleStatus',
  pool_health: 'poolHealth',
  task_status: 'taskStatus',
  suggestion_type: 'suggestionType',
  target_type: 'targetType',
  severity: 'severity',
  suggestion_reason: 'suggestionReason',
  policy_type: 'policyType',
  source_type: 'sourceType',
  invocation_status: 'invocationStatus',
  task_type: 'taskType',
  agent_pool: 'agentPool',
  tool_source_type: 'toolSourceType',
}

const translate = (key: string): string => {
  const v = i18n.global.t(key)
  // 未命中时 vue-i18n 返回 key 本身
  return typeof v === 'string' ? v : key
}

/**
 * 返回枚举值的语义文本；未知值原样返回（fallback 默认 '-'）。
 *
 * action 类值支持点分复合格式（如 "storage.file_delete"）：
 * 先按完整值查找，未命中时拆分为「资源前缀.file_delete」，
 * 前缀走 resourceType、后缀走 action 分别翻译后组合（如 "存储文件 · 删除"）。
 */
export const semanticLabel = (
  key: string,
  value: string | undefined | null,
  fallback = '-',
): string => {
  if (value == null || value === '') return fallback
  const category = CATEGORY_KEY_MAP[key]
  if (!category) return value
  const full = `semantic.${category}.${value}`
  const translated = translate(full)
  if (translated !== full) return translated
  if (category === 'action' && value.includes('.')) {
    const [prefix, ...rest] = value.split('.')
    const suffix = rest.join('.')
    if (prefix && suffix) {
      const prefixLabel = semanticLabel('resource_type', prefix)
      const suffixLabel = semanticLabel('action', suffix)
      if (prefixLabel !== prefix && suffixLabel !== suffix) {
        return `${prefixLabel} · ${suffixLabel}`
      }
      if (prefixLabel !== prefix) return prefixLabel
      if (suffixLabel !== suffix) return suffixLabel
    }
  }
  return value
}

/**
 * 返回枚举值的英文原值（供悬停浮窗显示原始标记）。
 * 已是最新语义文本时返回 undefined，调用方可据此决定是否展示 tooltip。
 */
export const semanticHint = (
  key: string,
  value: string | undefined | null,
): string | undefined => {
  if (value == null || value === '') return undefined
  const category = CATEGORY_KEY_MAP[key]
  if (!category) return undefined
  const translated = translate(`semantic.${category}.${value}`)
  return translated !== `semantic.${category}.${value}` ? value : undefined
}

/** 判断某枚举值是否存在已知语义映射 */
export const hasSemantic = (
  key: string,
  value: string | undefined | null,
): boolean => {
  if (value == null || value === '') return false
  const category = CATEGORY_KEY_MAP[key]
  if (!category) return false
  const translated = translate(`semantic.${category}.${value}`)
  return translated !== `semantic.${category}.${value}`
}

/** 截断 ID：uuid 或超长内部标识（无 @）截断保留前 8 位；邮箱/可读短名原样返回 */
export const truncateId = (id: string | null | undefined, head = 8): string => {
  if (!id) return ''
  if (id.includes('@')) return id
  return id.length > head ? `${id.slice(0, head)}...` : id
}

/** 是否为 uuid 形态（便于 UI 判断是否需要用可读名/悬停替代） */
export const isUuidLike = (value: string | null | undefined): boolean => {
  if (!value) return false
  return /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(value)
}
