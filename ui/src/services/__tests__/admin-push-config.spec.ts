import { beforeEach, describe, expect, it, vi } from 'vitest'
import { getPushConfig, savePushConfig, testPushSend } from '@/services/admin-push-config'
import * as request from '@/utils/request'

vi.mock('@/utils/request', () => ({
  get: vi.fn(),
  put: vi.fn(),
  post: vi.fn(),
}))

describe('admin push config service', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('loads push config', async () => {
    vi.mocked(request.get).mockResolvedValue({ data: { configs: { enabled: false } } } as never)

    const configs = await getPushConfig()

    expect(request.get).toHaveBeenCalledWith('/admin/push-config')
    expect(configs).toEqual({ enabled: false })
  })

  it('saves push config', async () => {
    const payload = { enabled: true, primary_provider: 'getui' as const }
    vi.mocked(request.put).mockResolvedValue({ data: { configs: payload } } as never)

    await savePushConfig(payload as never)

    expect(request.put).toHaveBeenCalledWith('/admin/push-config', { body: { configs: payload } })
  })

  it('sends test push to a device token', async () => {
    vi.mocked(request.post).mockResolvedValue({ data: { ok: true } } as never)

    await testPushSend('umeng', 'dt-1')

    expect(request.post).toHaveBeenCalledWith('/admin/push-config/test', {
      body: { provider: 'umeng', device_token: 'dt-1' },
    })
  })
})
