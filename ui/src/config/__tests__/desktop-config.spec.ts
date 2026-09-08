import { describe, expect, it, vi, afterEach } from 'vitest'
import { resolveEndpointResolution } from '@/config'

describe('resolveEndpointResolution desktop override', () => {
  afterEach(() => {
    delete (window as unknown as Record<string, unknown>).__DESKTOP_CONFIG__
    vi.unstubAllEnvs()
  })

  it('prefers window.__DESKTOP_CONFIG__ apiBase over origin fallback', () => {
    ;(window as unknown as Record<string, unknown>).__DESKTOP_CONFIG__ = {
      apiBase: 'https://cloud.example.com/api',
      socketUrl: 'https://cloud.example.com',
      socketPath: '/api/socket.io',
    }
    const res = resolveEndpointResolution({
      origin: 'https://fallback.example.com',
    } as Location)
    expect(res.apiBaseUrl).toBe('https://cloud.example.com/api')
    expect(res.socketEndpoint.url).toBe('https://cloud.example.com')
    expect(res.socketEndpoint.path).toBe('/api/socket.io')
  })

  it('falls back to location.origin /api when no desktop override', () => {
    const res = resolveEndpointResolution({
      origin: 'https://web.example.com',
    } as Location)
    expect(res.apiBaseUrl).toBe('https://web.example.com/api')
  })
})
