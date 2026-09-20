import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('@/utils/request', () => ({
  get: vi.fn(),
}))

import { getStorageUsage, resolveUpgradeUrl } from '@/services/storage-usage'
import * as request from '@/utils/request'

describe('storage usage service', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('调 GET /space/storage/usage 并返回用量概览', async () => {
    vi.mocked(request.get).mockResolvedValue({
      code: 'success',
      message: '',
      data: {
        total_bytes: 100,
        used_bytes: 30,
        remaining_bytes: 70,
        usage_percent: 30.0,
      },
    } as never)

    const resp = await getStorageUsage()

    expect(request.get).toHaveBeenCalledWith('/space/storage/usage')
    expect(resp.data.usage_percent).toBe(30.0)
    expect(resp.data.remaining_bytes).toBe(70)
  })

  it('扩容跳转指向会员中心', () => {
    expect(resolveUpgradeUrl()).toBe('/membership')
  })
})