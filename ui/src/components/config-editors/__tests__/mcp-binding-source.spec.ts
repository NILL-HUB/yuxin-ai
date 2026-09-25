import { describe, expect, it } from 'vitest'
import { resolveBindingCredentials } from '@/components/config-editors/mcp-binding-source'

const CIPHER = 'gAAAAABm-real-cipher-text'
const MASKED = 'sk-R******CRET'

describe('resolveBindingCredentials', () => {
  it('prefers the encrypted binding value over the masked top-level value', () => {
    const payload = {
      headers: [{ key: 'Authorization', value: 'Bea***oken' }],
      env: { ARK_API_KEY: MASKED },
      binding: {
        headers: [{ key: 'Authorization', value: CIPHER }],
        env: { ARK_API_KEY: CIPHER },
      },
    }

    const result = resolveBindingCredentials(payload)

    expect(result.env).toEqual({ ARK_API_KEY: CIPHER })
    expect(result.headers).toEqual([{ key: 'Authorization', value: CIPHER }])
  })

  it('never returns a masked value when the binding holds the cipher', () => {
    const payload = {
      env: { ARK_API_KEY: MASKED },
      binding: { env: { ARK_API_KEY: CIPHER } },
    }

    const result = resolveBindingCredentials(payload)

    expect(String(result.env.ARK_API_KEY)).not.toContain('*')
  })

  it('falls back to the top-level value when the binding has none', () => {
    const payload = {
      env: { PLAIN: 'value' },
      binding: {},
    }

    const result = resolveBindingCredentials(payload)

    expect(result.env).toEqual({ PLAIN: 'value' })
  })

  it('returns empty defaults when neither source is present', () => {
    const result = resolveBindingCredentials({})

    expect(result.env).toEqual({})
    expect(result.headers).toEqual([])
  })

  it('tolerates a non-object binding', () => {
    const payload = { env: { A: '1' }, binding: null }

    const result = resolveBindingCredentials(payload as never)

    expect(result.env).toEqual({ A: '1' })
  })
})
