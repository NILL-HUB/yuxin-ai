import { get, put } from '@/utils/request'
import type { BaseResponse } from '@/models/base'

export interface DesktopClientConfigPayload {
  /** 桌面端连接地址（http(s):// 开头；空表示与当前服务器同源） */
  api_origin: string
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
