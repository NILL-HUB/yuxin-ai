import { get, post, put } from '@/utils/request'
import {
  type PaymentConfigListResponse,
  type PaymentConfigStatusResponse,
} from '@/models/payment-config'

export const listPaymentConfigs = async () => {
  const response = await get<PaymentConfigListResponse>('/admin/payment-configs')
  return response.data
}

export const upsertPaymentConfig = async (provider: string, name: string, configs: Record<string, unknown>) => {
  const response = await put<PaymentConfigStatusResponse>(`/admin/payment-configs/${provider}`, {
    body: { name, configs },
  })
  return response.data
}

export const setPaymentConfigEnabled = async (provider: string, enabled: boolean) => {
  const response = await post<PaymentConfigStatusResponse>(`/admin/payment-configs/${provider}/enabled`, {
    body: { enabled },
  })
  return response.data
}