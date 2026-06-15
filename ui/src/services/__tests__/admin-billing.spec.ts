import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  createPlan,
  generateRedeemCodes,
  listPlans,
  listRedeemCodeBatches,
  listRedeemCodes,
  setPlanStatus,
  disableRedeemCode,
  disableRedeemCodeBatch,
  updatePlan,
} from '@/services/admin-billing'
import * as request from '@/utils/request'

vi.mock('@/utils/request', () => ({
  get: vi.fn(),
  post: vi.fn(),
}))

describe('admin billing service', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('lists plans with filters and pagination', async () => {
    vi.mocked(request.get).mockResolvedValue({ list: [], paginator: { total_record: 0 } } as never)

    await listPlans({ keyword: 'pro', status: 'active', current_page: 1, page_size: 20 })

    expect(request.get).toHaveBeenCalledWith('/admin/plans', {
      params: { keyword: 'pro', status: 'active', current_page: 1, page_size: 20 },
    })
  })

  it('creates and updates plans', async () => {
    const payload = {
      code: 'pro',
      name: 'Pro',
      duration_days: 30,
      grant_token_credits: 100000,
      price: '99.00',
      status: 'active' as const,
      entitlements: [{ feature_key: 'max_agents', feature_value: '10', value_type: 'number' as const }],
    }
    vi.mocked(request.post).mockResolvedValue({ id: 'plan-1' } as never)

    await createPlan(payload)
    await updatePlan('plan-1', { name: 'Pro Plus' })

    expect(request.post).toHaveBeenNthCalledWith(1, '/admin/plans', { body: payload })
    expect(request.post).toHaveBeenNthCalledWith(2, '/admin/plans/plan-1', { body: { name: 'Pro Plus' } })
  })

  it('sets plan status', async () => {
    vi.mocked(request.post).mockResolvedValue({ id: 'plan-1', status: 'disabled' } as never)

    await setPlanStatus('plan-1', 'disabled')

    expect(request.post).toHaveBeenCalledWith('/admin/plans/plan-1/status', { body: { status: 'disabled' } })
  })

  it('generates redeem codes and lists masked code records', async () => {
    vi.mocked(request.post).mockResolvedValue({ batch: { id: 'batch-1' }, codes: [{ plain_code: 'OA-ABC', code_mask: 'OAAB****C' }] } as never)
    vi.mocked(request.get).mockResolvedValue({ list: [], paginator: { total_record: 0 } } as never)

    await generateRedeemCodes({ name: 'Batch', plan_id: 'plan-1', quantity: 2 })
    await listRedeemCodeBatches({ keyword: 'Batch', current_page: 1, page_size: 20 })
    await listRedeemCodes({ batch_id: 'batch-1', status: 'unused', code_keyword: 'OAAB', current_page: 1, page_size: 20 })

    expect(request.post).toHaveBeenCalledWith('/admin/redeem-code-batches', { body: { name: 'Batch', plan_id: 'plan-1', quantity: 2 } })
    expect(request.get).toHaveBeenNthCalledWith(1, '/admin/redeem-code-batches', {
      params: { keyword: 'Batch', current_page: 1, page_size: 20 },
    })
    expect(request.get).toHaveBeenNthCalledWith(2, '/admin/redeem-codes', {
      params: { batch_id: 'batch-1', status: 'unused', code_keyword: 'OAAB', current_page: 1, page_size: 20 },
    })
  })

  it('disables redeem code and redeem code batch', async () => {
    vi.mocked(request.post).mockResolvedValue({ id: 'code-1', status: 'disabled' } as never)

    await disableRedeemCode('code-1')
    await disableRedeemCodeBatch('batch-1')

    expect(request.post).toHaveBeenNthCalledWith(1, '/admin/redeem-codes/code-1/disable')
    expect(request.post).toHaveBeenNthCalledWith(2, '/admin/redeem-code-batches/batch-1/disable')
  })
})
