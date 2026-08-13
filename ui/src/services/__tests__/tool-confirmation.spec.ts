import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  postToolConfirmationCancel,
  postToolConfirmationConfirm,
} from '@/services/tool-confirmation'
import * as request from '@/utils/request'

vi.mock('@/utils/request', () => ({
  get: vi.fn(),
  post: vi.fn(),
}))

describe('tool confirmation service', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('appends stable visitor id to confirm URL', async () => {
    vi.mocked(request.post).mockResolvedValue({ data: {} } as never)

    await postToolConfirmationConfirm('conf-1', 'visitor-123')

    expect(request.post).toHaveBeenCalledWith(
      '/tool-confirmations/conf-1/confirm?visitor_id=visitor-123',
    )
  })

  it('appends stable visitor id to cancel URL', async () => {
    vi.mocked(request.post).mockResolvedValue({ data: {} } as never)

    await postToolConfirmationCancel('conf-2', 'visitor-456')

    expect(request.post).toHaveBeenCalledWith(
      '/tool-confirmations/conf-2/cancel?visitor_id=visitor-456',
    )
  })
})
