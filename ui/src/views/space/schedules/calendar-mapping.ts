import type { IntervalConfig } from '@/services/schedule-task'

export type CalendarType = 'day' | 'week' | 'month' | 'minute' | 'hour'

export interface CalendarSelection {
  calType: CalendarType
  every: number
  hour: number
  minute: number
  weekday: number
  weekdays: number[]
  dayOfMonth: number
  calMinutes: number
}

const clamp = (value: number, min: number, max: number): number => Math.min(Math.max(value, min), max)
const positiveInt = (value: number): number => Math.max(1, Math.floor(Number(value) || 1))

// 去重 + 排序 + 限定 1~7，保证生成稳定的逗号列表
const normalizeWeekdays = (weekdays: number[]): number[] => [
  ...new Set(weekdays.map((d) => clamp(Math.floor(Number(d) || 0), 1, 7))),
].sort((a, b) => a - b)

// 天/周/月且 N=1 → cron；按分钟/按小时或每 N>1 → interval；
// 每周多选周几（如周一+周五）只能由 cron 表达 → 视为 cron
export const isIntervalCalendar = (calType: CalendarType, every: number, weekdays: number[] = []): boolean => {
  if (calType === 'week' && normalizeWeekdays(weekdays).length > 1) return false
  return calType === 'minute' || calType === 'hour' || every > 1
}

// 日历选择 → interval_config（仅在 isIntervalCalendar 成立时使用）
export const intervalConfigFromCalendar = (sel: CalendarSelection): IntervalConfig => {
  const every = positiveInt(sel.every)
  switch (sel.calType) {
    case 'minute':
      return { unit: 'minute', every }
    case 'hour':
      return { unit: 'hour', every, minutes: clamp(sel.calMinutes, 0, 59) }
    case 'week':
      return { unit: 'week', every, day_of_week: normalizeWeekdays(sel.weekdays)[0] ?? 1 }
    case 'month':
      return { unit: 'month', every, day_of_month: clamp(sel.dayOfMonth, 1, 31) }
    case 'day':
    default:
      return { unit: 'day', every, hours: clamp(sel.hour, 0, 23) }
  }
}

// 日历选择 → cron 表达式（天/周/月且 N=1 时使用；每周支持多个周几，如 1,5）
export const cronFromCalendar = (sel: CalendarSelection): string => {
  const hh = clamp(sel.hour, 0, 23)
  const mm = clamp(sel.minute, 0, 59)
  let cron = `0 ${mm} ${hh} * * *`
  if (sel.calType === 'week') cron = `0 ${mm} ${hh} * * ${normalizeWeekdays(sel.weekdays).join(',') || '1'}`
  if (sel.calType === 'month') cron = `0 ${mm} ${hh} ${clamp(sel.dayOfMonth, 1, 31)} * *`
  return cron
}

// interval_config → 日历选择状态（编辑回填 / 高级表单修改时联动）
export const calendarFromInterval = (config: IntervalConfig): CalendarSelection => {
  const every = positiveInt(config.every)
  const hours = clamp(Number(config.hours) || 0, 0, 23)
  const minutes = clamp(Number(config.minutes) || 0, 0, 59)
  const weekday = clamp(Number(config.day_of_week) || 1, 1, 7)
  const dayOfMonth = clamp(Number(config.day_of_month) || 1, 1, 31)
  switch (config.unit) {
    case 'minute':
      return { calType: 'minute', every, hour: 0, minute: 0, weekday: 1, weekdays: [1], dayOfMonth: 1, calMinutes: 0 }
    case 'hour':
      return { calType: 'hour', every, hour: 0, minute: 0, weekday: 1, weekdays: [1], dayOfMonth: 1, calMinutes: minutes }
    case 'week':
      return { calType: 'week', every, hour: 0, minute: 0, weekday, weekdays: [weekday], dayOfMonth: 1, calMinutes: 0 }
    case 'month':
      return { calType: 'month', every, hour: 0, minute: 0, weekday: 1, weekdays: [1], dayOfMonth, calMinutes: 0 }
    case 'day':
    default:
      return { calType: 'day', every, hour: hours, minute: 0, weekday: 1, weekdays: [1], dayOfMonth: 1, calMinutes: 0 }
  }
}
