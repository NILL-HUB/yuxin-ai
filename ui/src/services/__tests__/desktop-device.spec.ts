import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  listDesktopDevices,
  revokeDesktopDevice,
  updateDesktopDevice,
} from '@/services/desktop-device'
import * as request from '@/utils/request'

vi.mock('@/utils/request', () => ({
  get: vi.fn(),
  patch: vi.fn(),
  post: vi.fn(),
}))

describe('desktop device service', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('lists devices', async () => {
    vi.mocked(request.get).mockResolvedValue({ data: [] } as never)

    await listDesktopDevices()

    expect(request.get).toHaveBeenCalledWith('/desktop/devices')
  })

  it('renames a device via PATCH with encoded device id', async () => {
    vi.mocked(request.patch).mockResolvedValue({ data: {} } as never)

    await updateDesktopDevice('dev/1', { name: '客厅电脑' })

    expect(request.patch).toHaveBeenCalledWith('/desktop/devices/dev%2F1', {
      body: { name: '客厅电脑' },
    })
  })

  it('sets a device as default', async () => {
    vi.mocked(request.patch).mockResolvedValue({ data: {} } as never)

    await updateDesktopDevice('dev-1', { is_default: true })

    expect(request.patch).toHaveBeenCalledWith('/desktop/devices/dev-1', {
      body: { is_default: true },
    })
  })

  it('revokes a device', async () => {
    vi.mocked(request.post).mockResolvedValue({ data: { revoked: true } } as never)

    await revokeDesktopDevice('dev-1')

    expect(request.post).toHaveBeenCalledWith('/desktop/devices/dev-1/revoke')
  })
})
