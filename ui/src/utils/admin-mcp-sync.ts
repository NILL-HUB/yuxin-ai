/**
 * MCP 工具同步状态的展示语义（单一事实源）。
 *
 * 背景：后端 `mcp_provider.sync_status` 由 `api/internal/service/mcp_service.py`
 * 的 `sync_mcp_tools` 写入。历史缺陷：MCP 工具同步失败被**两层静默吞掉**
 * （工厂异常返回 []、调用方丢弃返回值），管理员误以为配置成功（体检 P0-5）。
 *
 * 取值语义：
 * - ''              从未尝试同步（迁移后既有行）
 * - ready           成功同步且至少 1 个工具
 * - empty           连接成功但服务端无工具
 * - failed          连接/协议/鉴权失败（原因见 sync_error）
 * - not_configured  前置缺失（transport 不受支持 / stdio 命令不可执行）
 */
import type { BaseResponse } from '@/models/base'

export type McpSyncTone = 'green' | 'orange' | 'red' | 'gray'

export type McpSyncDescriptor = {
  key: string
  color: McpSyncTone
  /** i18n 键，由调用方用 t() 解析 */
  labelKey: string
  raw: string
}

export const MCP_SYNC_STATUSES = ['', 'ready', 'empty', 'failed', 'not_configured'] as const

export const resolveMcpSyncDescriptor = (status?: string): McpSyncDescriptor => {
  const raw = String(status ?? '').trim()
  switch (raw) {
    case 'ready':
      return { key: 'ready', color: 'green', labelKey: 'admin.mcpAdmin.syncReady', raw }
    case 'empty':
      return { key: 'empty', color: 'orange', labelKey: 'admin.mcpAdmin.syncEmpty', raw }
    case 'not_configured':
      return {
        key: 'not_configured',
        color: 'orange',
        labelKey: 'admin.mcpAdmin.syncNotConfigured',
        raw,
      }
    case 'failed':
      return { key: 'failed', color: 'red', labelKey: 'admin.mcpAdmin.syncFailed', raw }
    default:
      // 未同步（''）或未知取值：不把裸英文码当文案展示
      return { key: 'unknown', color: 'gray', labelKey: 'admin.mcpAdmin.syncUnknown', raw }
  }
}

export type McpSyncNoticeLevel = 'success' | 'warning' | 'info' | 'error'

export type McpSyncNotice = { level: McpSyncNoticeLevel; messageKey: string }

/**
 * 同步接口返回后的提示语义：**不能用「接口 200」等同「已同步」**。
 */
export const resolveMcpSyncNotice = (status?: string): McpSyncNotice => {
  switch (String(status ?? '').trim()) {
    case 'ready':
      return { level: 'success', messageKey: 'admin.mcpAdmin.syncSucceeded' }
    case 'empty':
      return { level: 'warning', messageKey: 'admin.mcpAdmin.syncEmptyNotice' }
    case 'not_configured':
      return { level: 'warning', messageKey: 'admin.mcpAdmin.syncNotConfiguredNotice' }
    case 'failed':
      return { level: 'error', messageKey: 'admin.mcpAdmin.syncFailedNotice' }
    default:
      return { level: 'info', messageKey: 'admin.mcpAdmin.syncUnknownNotice' }
  }
}

export type McpSyncResult = {
  sync_status: string
  sync_error: string
  synced: number
}

export type McpSyncResponse = BaseResponse<McpSyncResult>
