import { beforeEach, describe, expect, it, vi } from 'vitest'
import { chatWithMyApp, listMyApps } from '@/services/my-apps'
import * as request from '@/utils/request'

vi.mock('@/utils/request', () => ({
  get: vi.fn(),
  ssePost: vi.fn(),
}))

describe('my apps service', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('lists my assigned AI apps', async () => {
    vi.mocked(request.get).mockResolvedValue({ list: [] } as never)

    await listMyApps()

    expect(request.get).toHaveBeenCalledWith('/my/apps')
  })

  it('chats with my assigned AI app through SSE', async () => {
    const onData = vi.fn()
    vi.mocked(request.ssePost).mockResolvedValue(undefined as never)

    await chatWithMyApp('app-1', { query: 'hello', image_urls: [], conversation_id: '' }, onData)

    expect(request.ssePost).toHaveBeenCalledWith('/my/apps/app-1/chat', {
      body: { query: 'hello', image_urls: [], conversation_id: '' },
    }, onData)
  })
})
