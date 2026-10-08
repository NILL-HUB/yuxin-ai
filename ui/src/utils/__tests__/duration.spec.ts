import { describe, expect, it } from 'vitest'
import { formatDuration, splitDuration } from '../duration'

const t = (key: string, named?: Record<string, unknown>) => {
  const unit = key.replace('common.duration.', '')
  const label = { seconds: '秒', minutes: '分钟', hours: '小时', days: '天' }[unit] ?? unit
  return `${named?.value ?? ''}${label}`
}

describe('splitDuration', () => {
  it('keeps sub-minute values in seconds', () => {
    expect(splitDuration(0)).toEqual({ value: 0, unit: 'seconds' })
    expect(splitDuration(18.163)).toEqual({ value: 18.16, unit: 'seconds' })
    expect(splitDuration(59.9)).toEqual({ value: 59.9, unit: 'seconds' })
  })

  it('rolls over to whole minutes at 60s (floor, never 0)', () => {
    expect(splitDuration(60)).toEqual({ value: 1, unit: 'minutes' })
    expect(splitDuration(119)).toEqual({ value: 1, unit: 'minutes' })
    expect(splitDuration(120)).toEqual({ value: 2, unit: 'minutes' })
    expect(splitDuration(3599)).toEqual({ value: 59, unit: 'minutes' })
  })

  it('rolls over to hours and days', () => {
    expect(splitDuration(3600)).toEqual({ value: 1, unit: 'hours' })
    expect(splitDuration(7200)).toEqual({ value: 2, unit: 'hours' })
    expect(splitDuration(86399)).toEqual({ value: 23, unit: 'hours' })
    expect(splitDuration(86400)).toEqual({ value: 1, unit: 'days' })
    expect(splitDuration(200000)).toEqual({ value: 2, unit: 'days' })
  })

  it('treats invalid input as zero seconds', () => {
    expect(splitDuration(Number.NaN)).toEqual({ value: 0, unit: 'seconds' })
    expect(splitDuration(-5)).toEqual({ value: 0, unit: 'seconds' })
  })
})

describe('formatDuration', () => {
  it('renders readable units instead of a bare "s" suffix', () => {
    expect(formatDuration(18.163, t)).toBe('18.16秒')
    expect(formatDuration(60, t)).toBe('1分钟')
    expect(formatDuration(3725.18, t)).toBe('1小时')
    expect(formatDuration(172800, t)).toBe('2天')
  })
})
