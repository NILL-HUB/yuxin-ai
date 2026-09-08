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

  it('posts confirm URL without visitor param', async () => {
    vi.mocked(request.post).mockResolvedValue({ data: {} } as never)

    await postToolConfirmationConfirm('conf-1')

    expect(request.post).toHaveBeenCalledWith('/tool-confirmations/conf-1/confirm')
  })

  it('posts cancel URL without visitor param', async () => {
    vi.mocked(request.post).mockResolvedValue({ data: {} } as never)

    await postToolConfirmationCancel('conf-2')

    expect(request.post).toHaveBeenCalledWith('/tool-confirmations/conf-2/cancel')
  })
})
