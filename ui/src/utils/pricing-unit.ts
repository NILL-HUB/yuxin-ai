// 界面统一以「/M tokens」口径录入与展示，而 DB/后端字段固定存「/1k tokens」
// （字段名 *_per_1k_tokens，成本=人民币元/1k，售价=算力/1k）。
// 换算关系：X_M = X_k × 1000；X_k = X_M ÷ 1000。

const PER_K_TO_PER_M_SCALE = 1000

// /1k → /M：×1000。非法/空输入返回 '0'，尾随 0 去尾后尽可能紧凑（如 '0.003000' → '3'）
export const perKToPerM = (value: string | number): string => {
  const n = Number(value)
  if (value === null || value === undefined || value === '' || !Number.isFinite(n)) return '0'
  return trimZeros((n * PER_K_TO_PER_M_SCALE).toFixed(6))
}

// /M → /1k：÷1000，保留 6 位小数。非法/空输入返回 '0.000000'
export const perMToPerK = (value: string | number): string => {
  const n = Number(value)
  if (value === null || value === undefined || value === '' || !Number.isFinite(n)) return '0.000000'
  return (n / PER_K_TO_PER_M_SCALE).toFixed(6)
}

const trimZeros = (raw: string): string => {
  if (raw.includes('.')) {
    const trimmed = raw.replace(/\.?0+$/, '')
    if (trimmed === '-') return '0'
    if (trimmed === '' || trimmed === '-0') return '0'
    return trimmed
  }
  return raw
}
