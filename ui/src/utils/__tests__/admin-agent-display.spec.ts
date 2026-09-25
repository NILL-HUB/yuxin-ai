import { describe, expect, it } from 'vitest'
import {
  AGENT_AVATAR_PALETTES,
  extractAvatarText,
  formatAgentTime,
  getAgentAvatarStyle,
  getAgentAvatarText,
  hashString,
} from '@/utils/admin-agent-display'

describe('admin-agent-display', () => {
  describe('hashString', () => {
    it('is deterministic for the same input', () => {
      expect(hashString('agent-1')).toBe(hashString('agent-1'))
    })

    it('differs across distinct inputs', () => {
      expect(hashString('agent-1')).not.toBe(hashString('agent-2'))
    })

    it('returns a non-negative 32-bit integer', () => {
      const value = hashString('池治理 Agent：sub-general')
      expect(Number.isInteger(value)).toBe(true)
      expect(value).toBeGreaterThanOrEqual(0)
      expect(value).toBeLessThan(2 ** 32)
    })

    it('handles empty input without throwing', () => {
      expect(() => hashString('')).not.toThrow()
      expect(hashString('')).toBe(0)
    })
  })

  describe('extractAvatarText', () => {
    it('uses the first letters of up to two latin words', () => {
      expect(extractAvatarText('Code Review Bot')).toBe('CR')
    })

    it('takes the first two chinese characters', () => {
      expect(extractAvatarText('巡检助手')).toBe('巡检')
    })

    it('handles a single latin word', () => {
      expect(extractAvatarText('agent')).toBe('A')
    })

    it('falls back to a placeholder for blank input', () => {
      expect(extractAvatarText('')).toBe('?')
      expect(extractAvatarText('   ')).toBe('?')
    })
  })

  describe('getAgentAvatarStyle', () => {
    it('is deterministic for the same seed', () => {
      expect(getAgentAvatarStyle('seed-a')).toEqual(getAgentAvatarStyle('seed-a'))
    })

    it('produces a linear-gradient background', () => {
      const style = getAgentAvatarStyle('seed-a')
      expect(style.background).toContain('linear-gradient')
    })

    it('only ever uses colors from the declared palette', () => {
      const allowed = new Set(AGENT_AVATAR_PALETTES.flatMap((pair) => [...pair]))
      for (const seed of ['a', 'b', 'c', 'pool-1', '子池', 'app::x']) {
        const style = getAgentAvatarStyle(seed)
        const colors = style.background.match(/#[0-9a-f]{6}/gi) || []
        expect(colors.length).toBeGreaterThan(0)
        colors.forEach((color) => {
          expect(allowed.has(color.toLowerCase())).toBe(true)
        })
      }
    })
  })

  describe('getAgentAvatarText', () => {
    it('delegates to extractAvatarText', () => {
      expect(getAgentAvatarText('巡检助手')).toBe(extractAvatarText('巡检助手'))
    })
  })

  describe('formatAgentTime', () => {
    it('returns the placeholder for empty values', () => {
      expect(formatAgentTime(null)).toBe('-')
      expect(formatAgentTime(undefined)).toBe('-')
      expect(formatAgentTime(0)).toBe('-')
    })

    it('honours a custom placeholder', () => {
      expect(formatAgentTime(null, '—')).toBe('—')
    })

    it('formats a second-level timestamp into a readable string', () => {
      const formatted = formatAgentTime(1700000000)
      expect(formatted).not.toBe('-')
      expect(formatted).not.toContain('Invalid')
    })
  })
})
