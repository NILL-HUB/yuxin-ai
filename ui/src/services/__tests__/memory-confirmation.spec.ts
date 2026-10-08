import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  cancelMemoryConfirmation,
  confirmMemoryConfirmation,
  getMemoryConfirmation,
} from '@/services/memory-confirmation'
import {
  cancelAgentMemoryConfirmation,
  confirmAgentMemoryConfirmation,
  getAgentMemoryConfirmation,
} from '@/services/admin-agents'
import * as request from '@/utils/request'

vi.mock('@/utils/request', () => ({
  get: vi.fn(),
  post: vi.fn(),
}))

describe('memory confirmation service', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('calls user-side detail / confirm / cancel endpoints', async () => {
    vi.mocked(request.get).mockResolvedValue({ data: {} } as never)
    vi.mocked(request.post).mockResolvedValue({ data: {} } as never)

    await getMemoryConfirmation('conf-1')
    await confirmMemoryConfirmation('conf-1')
    await cancelMemoryConfirmation('conf-1')

    expect(request.get).toHaveBeenCalledWith('/memory/confirmations/conf-1')
    expect(request.post).toHaveBeenCalledWith('/memory/confirmations/conf-1/confirm')
    expect(request.post).toHaveBeenCalledWith('/memory/confirmations/conf-1/cancel')
  })

  it('calls admin agent endpoints scoped by agent id', async () => {
    vi.mocked(request.get).mockResolvedValue({ data: {} } as never)
    vi.mocked(request.post).mockResolvedValue({ data: {} } as never)

    await getAgentMemoryConfirmation('agent-1', 'conf-2')
    await confirmAgentMemoryConfirmation('agent-1', 'conf-2')
    await cancelAgentMemoryConfirmation('agent-1', 'conf-2')

    expect(request.get).toHaveBeenCalledWith(
      '/admin/agents/agent-1/memory/confirmations/conf-2',
    )
    expect(request.post).toHaveBeenCalledWith(
      '/admin/agents/agent-1/memory/confirmations/conf-2/confirm',
    )
    expect(request.post).toHaveBeenCalledWith(
      '/admin/agents/agent-1/memory/confirmations/conf-2/cancel',
    )
  })
})
