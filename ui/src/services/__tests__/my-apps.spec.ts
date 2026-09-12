import { beforeEach, describe, expect, it, vi } from 'vitest'
import { chatWithMyApp, listMyApps } from '@/services/my-apps'
import { type MyAppListResponse } from '@/models/app-assignment'
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
    vi.mocked(request.get).mockResolvedValue({
      code: 'success',
      message: '',
      data: { list: [] },
    } as never)

    const res = await listMyApps()

    expect(request.get).toHaveBeenCalledWith('/my/apps')
    // get<T> 运行时返回完整信封，调用方须按 res.data.list 取值
    expect(res.data.list).toEqual([])
  })

  // 类型级断言：泛型若误写为 MyAppListResponse['data']，则 res.data 访问在本用例与
  // 上一用例都会在 `vue-tsc -p tsconfig.vitest.json` 下报 TS2339（运行时不体现，
  // 因 vitest 不做类型检查，故需专门的类型检查兜底）。
  it('listMyApps is typed as the full response envelope', async () => {
    vi.mocked(request.get).mockResolvedValue({ code: 'success', message: '', data: { list: [] } } as never)

    const res: MyAppListResponse = await listMyApps()

    expect(res.data.list).toEqual([])
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
