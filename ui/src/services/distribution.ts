import { get, put } from '@/utils/request'
import { apiPrefix } from '@/config'
import { getCredentialAccessToken, getStoredCredential } from '@/utils/auth'
import {
  type CommissionListResponse,
  type MyDistributionResponse,
  type SubordinateListResponse,
} from '@/models/distribution'

export const getMyDistribution = async () => {
  const response = await get<MyDistributionResponse>('/distribution/me')
  return response.data
}

export const listSubordinates = async (params: { current_page: number; page_size: number }) => {
  const response = await get<SubordinateListResponse>('/distribution/subordinates', { params })
  return response.data
}

export const listMyCommissions = async (params: { current_page: number; page_size: number }) => {
  const response = await get<CommissionListResponse>('/distribution/commissions', { params })
  return response.data
}

export const updateReferralCode = async (code: string) => {
  const response = await put<MyDistributionResponse>('/distribution/referral-code', { body: { code } })
  return response.data
}

export type DistributionQrcodeResult = {
  share_url: string
  qrcode_url: string | null
}

// /distribution/qrcode 优先返回 PNG 图片（qrcode 库可用时），否则降级返回 {share_url}。
// 泛型 request 只解析 JSON，二进制图片需单独 fetch 并转 object URL。
export const getDistributionQrcode = async (): Promise<DistributionQrcodeResult> => {
  const accessToken = getCredentialAccessToken(getStoredCredential())
  const headers: Record<string, string> = {}
  if (accessToken) {
    headers.Authorization = `Bearer ${accessToken}`
  }
  try {
    const response = await globalThis.fetch(`${apiPrefix}/distribution/qrcode`, {
      method: 'GET',
      credentials: 'include',
      headers,
    })
    const contentType = response.headers.get('Content-Type') || ''
    if (contentType.includes('image')) {
      const blob = await response.blob()
      return { share_url: '', qrcode_url: URL.createObjectURL(blob) }
    }
    const json = (await response.json()) as { data?: { share_url?: string } }
    return { share_url: json?.data?.share_url || '', qrcode_url: null }
  } catch {
    return { share_url: '', qrcode_url: null }
  }
}