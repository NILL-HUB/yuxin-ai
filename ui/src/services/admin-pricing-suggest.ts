import { apiPrefix } from '@/config'
import { getAdminCredentialAccessToken, getStoredAdminCredential } from '@/utils/admin-auth'

export interface PricingSuggestResp {
  ok: boolean
  data: Record<string, string>
  message?: string
}

// /admin/model-pools/pricing-suggest 返回裸 {ok, data}（不走标准 {code,message,data} 信封），
// 泛型 request 的 isApiResponse 校验无法识别该结构，故参照 distribution.ts 对非标准响应直接 fetch。
export const suggestSellPrices = async (
  fields: Record<string, unknown>,
  marginRatio = 0.3,
): Promise<PricingSuggestResp> => {
  const accessToken = getAdminCredentialAccessToken(getStoredAdminCredential())
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  if (accessToken) {
    headers.Authorization = `Bearer ${accessToken}`
  }
  const response = await globalThis.fetch(`${apiPrefix}/admin/model-pools/pricing-suggest`, {
    method: 'POST',
    credentials: 'include',
    headers,
    body: JSON.stringify({ fields, margin_ratio: marginRatio }),
  })
  const json = (await response.json()) as PricingSuggestResp
  if (!response.ok) {
    const message =
      typeof json?.message === 'string' && json.message ? json.message : `HTTP ${response.status}`
    throw new Error(message)
  }
  return json
}