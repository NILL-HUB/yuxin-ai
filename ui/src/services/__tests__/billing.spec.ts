import { beforeEach, describe, expect, it, vi } from 'vitest'
import { getMembershipSummary, getRedeemRecords, redeemCode } from '@/services/billing'
import * as request from '@/utils/request'

vi.mock('@/utils/request', () => ({
  get: vi.fn(),
  post: vi.fn(),
}))

describe('billing service', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('redeems code', async () => {
    vi.mocked(request.post).mockResolvedValue({ credit_account: { balance: 100000 } } as never)

    await redeemCode('OA-ABC')

    expect(request.post).toHaveBeenCalledWith('/redeem-codes/redeem', { body: { code: 'OA-ABC' } })
  })

  it('gets membership summary', async () => {
    vi.mocked(request.get).mockResolvedValue({ membership: null, credit_account: { balance: 0 }, recent_transactions: [] } as never)

    await getMembershipSummary()

    expect(request.get).toHaveBeenCalledWith('/membership/summary')
  })

  it('gets redeem records', async () => {
    vi.mocked(request.get).mockResolvedValue({ list: [] } as never)

    await getRedeemRecords()

    expect(request.get).toHaveBeenCalledWith('/membership/redeem-records')
  })
})
