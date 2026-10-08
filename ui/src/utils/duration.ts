/**
 * 用户可读的耗时格式化（聊天卡片 / 推理步骤共用）。
 *
 * 规则（2026-10-08 产品要求）：不足 1 分钟保留两位小数、单位用中文「秒」；
 * 超过 1 分钟进位为整「分钟」，再往上依次「小时」「天」（向下取整）。
 * 为什么不用 `toFixed(2) + "s"`：英文单位用户看不懂，长任务显示 3725.18s 也没有意义。
 *
 * 单位文案走 i18n（`common.duration.*`，含 {value} 插值），本模块只负责分段。
 */
export type DurationTranslate = (key: string, named?: Record<string, unknown>) => string

const SECONDS_PER_MINUTE = 60
const SECONDS_PER_HOUR = 3600
const SECONDS_PER_DAY = 86400

/** 把秒数切成「数值 + 单位键」，便于测试与自定义渲染。 */
export const splitDuration = (seconds: number): { value: number; unit: 'seconds' | 'minutes' | 'hours' | 'days' } => {
  const value = Number(seconds)
  if (!Number.isFinite(value) || value < SECONDS_PER_MINUTE) {
    return { value: Number.isFinite(value) && value > 0 ? Number(value.toFixed(2)) : 0, unit: 'seconds' }
  }
  if (value < SECONDS_PER_HOUR) {
    return { value: Math.floor(value / SECONDS_PER_MINUTE), unit: 'minutes' }
  }
  if (value < SECONDS_PER_DAY) {
    return { value: Math.floor(value / SECONDS_PER_HOUR), unit: 'hours' }
  }
  return { value: Math.floor(value / SECONDS_PER_DAY), unit: 'days' }
}

export const formatDuration = (seconds: number, t: DurationTranslate): string => {
  const { value, unit } = splitDuration(seconds)
  if (unit === 'seconds') {
    return t('common.duration.seconds', { value: value.toFixed(2) })
  }
  return t(`common.duration.${unit}`, { value })
}
