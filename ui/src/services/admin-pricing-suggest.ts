import { post } from '@/utils/request'
import type { BaseResponse } from '@/models/base'

export type PricingSuggestResp = BaseResponse<Record<string, string>>

export const suggestSellPrices = async (
  fields: Record<string, unknown>,
  marginRatio = 0.3,
): Promise<Record<string, string>> => {
  const response = await post<PricingSuggestResp>('/admin/model-pools/pricing-suggest', {
    body: { fields, margin_ratio: marginRatio },
  })
  return response.data
}
