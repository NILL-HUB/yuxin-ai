const fs = require('node:fs')
const path = require('node:path')

const DEFAULT_BOUNDS = { width: 1280, height: 860 }
const MIN_WIDTH = 940
const MIN_HEIGHT = 620
// 至少保留这么多像素可见，避免显示器拔出后标题栏拖不到
const MIN_VISIBLE = 48

const finite = (v) => typeof v === 'number' && Number.isFinite(v)

function sanitize(raw) {
  if (!raw || typeof raw !== 'object' || !finite(raw.width) || !finite(raw.height)) {
    return null
  }
  const state = {
    width: Math.max(MIN_WIDTH, Math.round(raw.width)),
    height: Math.max(MIN_HEIGHT, Math.round(raw.height)),
    isMaximized: raw.isMaximized === true,
  }
  if (finite(raw.x) && finite(raw.y)) {
    state.x = Math.round(raw.x)
    state.y = Math.round(raw.y)
  }
  return state
}

function onAnyScreen(bounds, displays) {
  if (!Array.isArray(displays)) return false
  return displays.some(({ workArea: a } = {}) => {
    if (!a) return false
    const ox = Math.min(bounds.x + bounds.width, a.x + a.width) - Math.max(bounds.x, a.x)
    const oy = Math.min(bounds.y + bounds.height, a.y + a.height) - Math.max(bounds.y, a.y)
    return ox >= MIN_VISIBLE && oy >= MIN_VISIBLE
  })
}

function computeWindowOptions(state, displays) {
  const opts = {
    width: finite(state && state.width) ? state.width : DEFAULT_BOUNDS.width,
    height: finite(state && state.height) ? state.height : DEFAULT_BOUNDS.height,
  }
  const largest = (Array.isArray(displays) ? displays : []).reduce(
    (m, { workArea: a } = {}) => (a && finite(a.width) && finite(a.height) ? {
      width: Math.max(m.width, a.width),
      height: Math.max(m.height, a.height),
    } : m),
    { width: 0, height: 0 },
  )
  if (largest.width && largest.height) {
    opts.width = Math.min(Math.max(opts.width, MIN_WIDTH), largest.width)
    opts.height = Math.min(Math.max(opts.height, MIN_HEIGHT), largest.height)
  }
  if (
    state &&
    finite(state.x) &&
    finite(state.y) &&
    onAnyScreen({ x: state.x, y: state.y, width: opts.width, height: opts.height }, displays)
  ) {
    opts.x = state.x
    opts.y = state.y
  }
  return opts
}

function loadState(filePath) {
  try {
    return sanitize(JSON.parse(fs.readFileSync(filePath, 'utf-8')))
  } catch {
    return null
  }
}

function saveState(filePath, win) {
  try {
    if (!win || win.isDestroyed()) return
    const isMaximized = win.isMaximized()
    const bounds = win.getNormalBounds()
    fs.mkdirSync(path.dirname(filePath), { recursive: true })
    fs.writeFileSync(
      filePath,
      JSON.stringify({ ...bounds, isMaximized }, null, 2),
      'utf-8',
    )
  } catch {
    // 写入失败可忽略（如磁盘只读）
  }
}

module.exports = {
  DEFAULT_BOUNDS,
  MIN_HEIGHT,
  MIN_WIDTH,
  computeWindowOptions,
  loadState,
  saveState,
}
