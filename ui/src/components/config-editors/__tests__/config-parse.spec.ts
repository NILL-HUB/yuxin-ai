import { describe, expect, it } from 'vitest'
import {
  ConfigParseError,
  formatJson,
  isValidJsonArray,
  isValidJsonObject,
  joinCommaList,
  parseJsonArray,
  parseJsonObject,
  splitCommaList,
} from '@/components/config-editors/config-parse'

describe('config-parse', () => {
  describe('parseJsonObject', () => {
    it('returns empty object for blank input', () => {
      expect(parseJsonObject('')).toEqual({})
      expect(parseJsonObject('   ')).toEqual({})
      expect(parseJsonObject(null)).toEqual({})
    })

    it('parses a valid object', () => {
      expect(parseJsonObject('{"a":"1"}')).toEqual({ a: '1' })
    })

    it('throws invalidJson for malformed input', () => {
      try {
        parseJsonObject('{not-json')
        throw new Error('should have thrown')
      } catch (error) {
        expect(error).toBeInstanceOf(ConfigParseError)
        expect((error as ConfigParseError).code).toBe('invalidJson')
      }
    })

    it('throws objectExpected when given an array', () => {
      try {
        parseJsonObject('[]')
        throw new Error('should have thrown')
      } catch (error) {
        expect((error as ConfigParseError).code).toBe('objectExpected')
      }
    })
  })

  describe('parseJsonArray', () => {
    it('returns empty array for blank input', () => {
      expect(parseJsonArray('')).toEqual([])
    })

    it('parses a valid array', () => {
      expect(parseJsonArray('[1,2]')).toEqual([1, 2])
    })

    it('throws arrayExpected when given an object', () => {
      try {
        parseJsonArray('{}')
        throw new Error('should have thrown')
      } catch (error) {
        expect((error as ConfigParseError).code).toBe('arrayExpected')
      }
    })
  })

  describe('validators', () => {
    it('treats blank as valid (optional fields)', () => {
      expect(isValidJsonArray('')).toBe(true)
      expect(isValidJsonObject('')).toBe(true)
    })

    it('reports shape mismatches', () => {
      expect(isValidJsonArray('{}')).toBe(false)
      expect(isValidJsonObject('[]')).toBe(false)
      expect(isValidJsonArray('[1]')).toBe(true)
      expect(isValidJsonObject('{"a":1}')).toBe(true)
    })

    it('reports malformed json', () => {
      expect(isValidJsonArray('[1')).toBe(false)
      expect(isValidJsonObject('{')).toBe(false)
    })
  })

  describe('formatJson', () => {
    it('pretty prints values', () => {
      expect(formatJson({ a: 1 })).toBe('{\n  "a": 1\n}')
    })

    it('returns fallback for nullish input', () => {
      expect(formatJson(undefined, '[]')).toBe('[]')
    })
  })

  describe('comma list helpers', () => {
    it('splits on both ascii and full-width commas', () => {
      expect(splitCommaList('a, b，c')).toEqual(['a', 'b', 'c'])
    })

    it('drops empty entries', () => {
      expect(splitCommaList(' a , , b ')).toEqual(['a', 'b'])
    })

    it('joins with ascii comma and space', () => {
      expect(joinCommaList(['a', 'b'])).toBe('a, b')
      expect(joinCommaList(null)).toBe('')
    })

    it('round-trips', () => {
      expect(splitCommaList(joinCommaList(['x', 'y']))).toEqual(['x', 'y'])
    })
  })
})
