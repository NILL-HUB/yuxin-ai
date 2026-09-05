import { type BaseResponse } from '@/models/base'

export type PaymentConfig = {
  provider: string
  name: string
  enabled: boolean
  configs: Record<string, unknown>
  updated_at: number | null
}

export type PaymentConfigListData = { list: PaymentConfig[] }
export type PaymentConfigListResponse = BaseResponse<PaymentConfigListData>
export type PaymentConfigStatusResponse = BaseResponse<{ provider: string; enabled: boolean }>