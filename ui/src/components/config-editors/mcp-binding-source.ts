export type McpProviderPayloadLike = {
  headers?: unknown
  env?: unknown
  binding?: unknown
}

const asRecord = (value: unknown): Record<string, unknown> => {
  if (value && typeof value === 'object' && !Array.isArray(value)) {
    return value as Record<string, unknown>
  }
  return {}
}

const hasContent = (value: unknown): boolean => {
  if (Array.isArray(value)) return value.length > 0
  if (value && typeof value === 'object') return Object.keys(value as Record<string, unknown>).length > 0
  return false
}

/**
 * 解析编辑回填应使用的 headers/env。
 *
 * 后端详情接口对**顶层** headers/env 脱敏（形如 `sk-R******CRET`），凭证密文
 * 保存在 `payload.binding` 中（mcp_service._build_provider_payload 注释：
 * "binding 字段保留原始（加密）值，供前端存入 app_config 后由 McpToolFactory
 * 在运行时统一调用 decrypt_headers/decrypt_env 还原"）。
 *
 * 编辑态必须优先取 binding：若误用顶层脱敏值回填，用户未改动直接保存会经
 * encrypt_env(掩码) 把真实密钥覆盖成掩码，且不可逆。
 */
export const resolveBindingCredentials = (payload: McpProviderPayloadLike) => {
  const binding = asRecord(payload?.binding)
  const pick = (field: 'headers' | 'env'): unknown => {
    const fromBinding = binding[field]
    if (hasContent(fromBinding)) return fromBinding
    const fromTop = payload?.[field]
    if (hasContent(fromTop)) return fromTop
    return field === 'headers' ? [] : {}
  }
  return {
    headers: pick('headers'),
    env: pick('env'),
  }
}
