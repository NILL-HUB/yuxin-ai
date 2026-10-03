import { get, post, put } from '@/utils/request'
import type { BaseResponse } from '@/models/base'

export interface DesktopClientConfigPayload {
  /** 桌面端连接地址（http(s):// 开头；空表示与当前服务器同源） */
  api_origin: string
  /** 更新包托管地址（electron-builder generic provider 的 base url；空表示未配置） */
  update_feed_url: string
  /** 是否向客户端推送更新（关闭后客户端静默跳过检查） */
  update_enabled: boolean
}

/** 检查更新包目录的结果（读上游 latest.yml 解析） */
export interface DesktopUpdateCheckResult {
  ok: boolean
  feed_url?: string
  latest_url?: string
  latest_version?: string
  release_notes?: string
  release_date?: string
  package_path?: string
  /** 拉取失败时的原因摘要 */
  detail?: string
}

export const getDesktopClientConfig = async (): Promise<DesktopClientConfigPayload> => {
  const response = await get<BaseResponse<{ configs: DesktopClientConfigPayload }>>('/admin/desktop-client-config')
  return response.data.configs
}

export const saveDesktopClientConfig = async (
  configs: DesktopClientConfigPayload,
): Promise<DesktopClientConfigPayload> => {
  const response = await put<BaseResponse<{ configs: DesktopClientConfigPayload }>>('/admin/desktop-client-config', {
    body: { configs },
  })
  return response.data.configs
}

/** 检查更新包目录下是否有可下发的版本（不修改任何状态） */
export const checkDesktopUpdate = async (): Promise<DesktopUpdateCheckResult> => {
  const response = await post<BaseResponse<DesktopUpdateCheckResult>>('/admin/desktop-update/check')
  return response.data
}
