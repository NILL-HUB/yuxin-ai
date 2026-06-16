import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  getAdminOrchestrationReleaseCheck,
  listAdminOrchestrationFlags,
  updateAdminOrchestrationFlag,
} from '@/services/admin-orchestration-flags'
import * as request from '@/utils/request'

vi.mock('@/utils/request', () => ({
  get: vi.fn(),
  post: vi.fn(),
}))

describe('admin orchestration flags service', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('lists orchestration flags', async () => {
    vi.mocked(request.get).mockResolvedValue([] as never)

    await listAdminOrchestrationFlags()

    expect(request.get).toHaveBeenCalledWith('/admin/orchestration-flags')
  })

  it('updates orchestration flag state', async () => {
    vi.mocked(request.post).mockResolvedValue({ enabled: false } as never)

    await updateAdminOrchestrationFlag('ENABLE_ORCHESTRATOR', { enabled: false })

    expect(request.post).toHaveBeenCalledWith(
      '/admin/orchestration-flags/ENABLE_ORCHESTRATOR',
      { body: { enabled: false } },
    )
  })

  it('gets release check report', async () => {
    vi.mocked(request.get).mockResolvedValue({ warnings: [] } as never)

    await getAdminOrchestrationReleaseCheck()

    expect(request.get).toHaveBeenCalledWith('/admin/orchestration-release-check')
  })
})
