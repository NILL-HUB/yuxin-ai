import { describe, expect, it } from 'vitest'

import {
  calendarFromInterval,
  cronFromCalendar,
  intervalConfigFromCalendar,
  isIntervalCalendar,
} from '../calendar-mapping'

const base = {
  hour: 14,
  minute: 30,
  weekday: 3,
  weekdays: [3],
  dayOfMonth: 5,
  calMinutes: 25,
}

describe('isIntervalCalendar', () => {
  it('每天/每周/每月且 N=1 时是 cron', () => {
    expect(isIntervalCalendar('day', 1)).toBe(false)
    expect(isIntervalCalendar('week', 1)).toBe(false)
    expect(isIntervalCalendar('month', 1)).toBe(false)
  })

  it('按分钟/按小时始终是 interval', () => {
    expect(isIntervalCalendar('minute', 1)).toBe(true)
    expect(isIntervalCalendar('hour', 1)).toBe(true)
  })

  it('每 N>1 天/周/月是 interval', () => {
    expect(isIntervalCalendar('day', 2)).toBe(true)
    expect(isIntervalCalendar('week', 3)).toBe(true)
    expect(isIntervalCalendar('month', 12)).toBe(true)
  })

  it('每周多选周几（如周一+周五）是 cron', () => {
    expect(isIntervalCalendar('week', 1, [1, 5])).toBe(false)
    expect(isIntervalCalendar('week', 3, [1, 5])).toBe(false)
  })

  it('每周单选周几且 N>1 仍是 interval', () => {
    expect(isIntervalCalendar('week', 2, [5])).toBe(true)
  })
})

describe('intervalConfigFromCalendar', () => {
  it('按分钟：只带 every', () => {
    expect(intervalConfigFromCalendar({ ...base, calType: 'minute', every: 30 })).toEqual({
      unit: 'minute',
      every: 30,
    })
  })

  it('按小时：带分点', () => {
    expect(intervalConfigFromCalendar({ ...base, calType: 'hour', every: 2 })).toEqual({
      unit: 'hour',
      every: 2,
      minutes: 25,
    })
  })

  it('每 N 天：带小时（固定整点）', () => {
    expect(intervalConfigFromCalendar({ ...base, calType: 'day', every: 2 })).toEqual({
      unit: 'day',
      every: 2,
      hours: 14,
    })
  })

  it('每 N 周（单选）：带周几', () => {
    expect(intervalConfigFromCalendar({ ...base, calType: 'week', every: 2 })).toEqual({
      unit: 'week',
      every: 2,
      day_of_week: 3,
    })
  })

  it('每 N 月：带几号', () => {
    expect(intervalConfigFromCalendar({ ...base, calType: 'month', every: 3 })).toEqual({
      unit: 'month',
      every: 3,
      day_of_month: 5,
    })
  })

  it('every 非法值回退为 1', () => {
    expect(intervalConfigFromCalendar({ ...base, calType: 'day', every: 0 })).toEqual({
      unit: 'day',
      every: 1,
      hours: 14,
    })
  })
})

describe('cronFromCalendar', () => {
  it('每天：0 分 时 * * *', () => {
    expect(cronFromCalendar({ ...base, calType: 'day', every: 1 })).toBe('0 30 14 * * *')
  })

  it('每周单选：带上周几', () => {
    expect(cronFromCalendar({ ...base, calType: 'week', every: 1 })).toBe('0 30 14 * * 3')
  })

  it('每周多选：周几用逗号连接且有序', () => {
    expect(cronFromCalendar({ ...base, calType: 'week', every: 1, weekdays: [5, 1] })).toBe('0 30 14 * * 1,5')
  })

  it('每周多选：周日为 7', () => {
    expect(cronFromCalendar({ ...base, calType: 'week', every: 1, weekdays: [1, 7] })).toBe('0 30 14 * * 1,7')
  })

  it('每月：带上几号', () => {
    expect(cronFromCalendar({ ...base, calType: 'month', every: 1 })).toBe('0 30 14 5 * *')
  })
})

describe('calendarFromInterval', () => {
  it('minute → 按分钟', () => {
    expect(calendarFromInterval({ unit: 'minute', every: 5 })).toMatchObject({
      calType: 'minute',
      every: 5,
    })
  })

  it('hour → 按小时并回填分点', () => {
    expect(calendarFromInterval({ unit: 'hour', every: 2, minutes: 30 })).toMatchObject({
      calType: 'hour',
      every: 2,
      calMinutes: 30,
    })
  })

  it('day → 每天并回填小时', () => {
    expect(calendarFromInterval({ unit: 'day', every: 2, hours: 8 })).toMatchObject({
      calType: 'day',
      every: 2,
      hour: 8,
    })
  })

  it('week → 每周并回填周几', () => {
    expect(calendarFromInterval({ unit: 'week', every: 2, day_of_week: 6 })).toMatchObject({
      calType: 'week',
      every: 2,
      weekdays: [6],
    })
  })

  it('month → 每月并回填几号', () => {
    expect(calendarFromInterval({ unit: 'month', every: 3, day_of_month: 15 })).toMatchObject({
      calType: 'month',
      every: 3,
      dayOfMonth: 15,
    })
  })

  it('day_of_week 缺省时回退为周一', () => {
    expect(calendarFromInterval({ unit: 'week', every: 1 })).toMatchObject({ weekdays: [1] })
  })

  it('日历→interval→日历 往返一致', () => {
    const sel = { ...base, calType: 'day' as const, every: 2 }
    const back = calendarFromInterval(intervalConfigFromCalendar(sel))
    expect(back).toMatchObject({ calType: 'day', every: 2, hour: 14 })
  })
})
