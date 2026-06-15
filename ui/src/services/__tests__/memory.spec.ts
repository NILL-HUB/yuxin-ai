import { beforeEach, describe, expect, it, vi } from 'vitest'
import { confirmMemoryCandidate, ignoreMemoryCandidate } from '@/services/memory'
import * as requestModule from '@/utils/request'

vi.mock('@/utils/request', () => ({
  post: vi.fn(),
}))

describe('memory service', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('confirms a memory candidate with manual policy', async () => {
    vi.mocked(requestModule.post).mockResolvedValue({ id: 'memory-1' } as never)

    await confirmMemoryCandidate('candidate-1', { policy: 'manual_confirm' })

    expect(requestModule.post).toHaveBeenCalledWith(
      '/memory-candidates/candidate-1/confirm',
      { body: { policy: 'manual_confirm' } },
    )
  })

  it('confirms a memory candidate with auto save policy', async () => {
    vi.mocked(requestModule.post).mockResolvedValue({ id: 'memory-1' } as never)

    await confirmMemoryCandidate('candidate-1', { policy: 'auto_save' })

    expect(requestModule.post).toHaveBeenCalledWith(
      '/memory-candidates/candidate-1/confirm',
      { body: { policy: 'auto_save' } },
    )
  })

  it('ignores a memory candidate with never remind flag', async () => {
    vi.mocked(requestModule.post).mockResolvedValue({ id: 'candidate-1' } as never)

    await ignoreMemoryCandidate('candidate-1', { never_remind: true })

    expect(requestModule.post).toHaveBeenCalledWith(
      '/memory-candidates/candidate-1/ignore',
      { body: { never_remind: true } },
    )
  })
})
