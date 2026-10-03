import { get, patch, post } from '@/utils/request'
import type { BaseResponse } from '@/models/base'

export type DesktopDeviceStatus = 'online' | 'offline' | 'revoked'

export type DesktopDeviceItem = {
  device_id: string
  name: string
  platform: string
  bridge_origin: string
  is_default: boolean
  status: DesktopDeviceStatus | string
  last_seen_at: string | null
}

// 列出当前账号已注册的桌面设备（token 脱敏；在线态为服务端读时计算）
export const listDesktopDevices = () => get<BaseResponse<DesktopDeviceItem[]>>('/desktop/devices')

// 更新设备展示名 / 默认标记（重命名、设为默认；name / is_default 至少传一个）
export const updateDesktopDevice = (
  deviceId: string,
  payload: { name?: string; is_default?: boolean },
) =>
  patch<BaseResponse<DesktopDeviceItem>>(`/desktop/devices/${encodeURIComponent(deviceId)}`, {
    body: payload,
  })

// 解绑设备（吊销后服务端不再向该设备转发本机操作）
export const revokeDesktopDevice = (deviceId: string) =>
  post<BaseResponse<{ revoked: boolean }>>(
    `/desktop/devices/${encodeURIComponent(deviceId)}/revoke`,
  )
