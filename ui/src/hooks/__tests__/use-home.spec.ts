import { beforeEach, describe, expect, it, vi } from 'vitest'

import { useGetHomeIntent } from '@/hooks/use-home'
import * as homeService from '@/services/home'

vi.mock('@/services/home', () => ({
  getHomeIntent: vi.fn(),
}))

describe('useGetHomeIntent', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('returns intent data and resets loading on success', async () => {
    const payload = {
      intent: '创建天气应用',
      confidence: 0.92,
      should_ask_continue: true,
      resume_question: '上次你在创建天气应用，要不要继续？',
      suggested_actions: [{ label: '创建应用', action: 'create_app', icon: 'plus' }],
      is_default: false,
    }
    vi.mocked(homeService.getHomeIntent).mockResolvedValue({ data: payload } as never)

    const { loading, loadHomeIntent } = useGetHomeIntent()

    expect(loading.value).toBe(false)
    const result = await loadHomeIntent()

    expect(result).toEqual(payload)
    expect(homeService.getHomeIntent).toHaveBeenCalledTimes(1)
    expect(loading.value).toBe(false)
  })

  it('resets loading when request fails', async () => {
    vi.mocked(homeService.getHomeIntent).mockRejectedValue(new Error('network error'))

    const { loading, loadHomeIntent } = useGetHomeIntent()

    await expect(loadHomeIntent()).rejects.toThrow('network error')
    expect(loading.value).toBe(false)
  })
})
