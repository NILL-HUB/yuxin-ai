let autoUpdater = null
try {
  ;({ autoUpdater } = require('electron-updater'))
} catch {
  autoUpdater = null
}

// 启动延迟检查 + 每日巡检间隔。延迟是为了错开应用启动流程（窗口/worker/注册）。
const STARTUP_CHECK_DELAY_MS = 30 * 1000
const DAILY_CHECK_INTERVAL_MS = 24 * 60 * 60 * 1000

// 读取「更新推送门控清单」的超时（服务端 GET /desktop/update-manifest）。
const MANIFEST_TIMEOUT_MS = 8000

// 本次检查是否由用户手动触发：仅用于决定「已是最新版本」要不要提示用户。
// 自动巡检每天都会 not-available，若无差别地提示会变成噪音。
let manualCheckPending = false
let periodicTimer = null

// 由 main.js 注入：返回当前 API base（syncConfig().apiBase）。
// updater 不直接依赖 server-config，便于单测注入替身。
let apiBaseResolver = null

function configureUpdater({ getApiBase } = {}) {
  apiBaseResolver = typeof getApiBase === 'function' ? getApiBase : null
}

// 从 UpdateInfo 提取 UI 需要的字段：版本号 + 更新历程（releaseNotes 由发布端写进 latest.yml）
function pickUpdateInfo(info) {
  return {
    version: (info && info.version) || null,
    releaseNotes: normalizeReleaseNotes(info && info.releaseNotes),
  }
}

// electron-updater 的 releaseNotes 可能是 string、Array<{version, note}> 或 null，统一为字符串
function normalizeReleaseNotes(notes) {
  if (!notes) return ''
  if (typeof notes === 'string') return notes.trim()
  if (Array.isArray(notes)) {
    return notes
      .map((item) => (item && item.note) || '')
      .filter(Boolean)
      .join('\n')
      .trim()
  }
  return ''
}

// 检查更新前读取服务端门控清单：管理员关闭推送（enabled=false）时客户端静默跳过。
// 返回 null 表示不可达（接口失败/无 apiBase），调用方按「保持既有行为」降级。
async function fetchUpdateManifest() {
  if (!apiBaseResolver) return null
  const apiBase = String(apiBaseResolver() || '').replace(/\/+$/, '')
  if (!apiBase) return null
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), MANIFEST_TIMEOUT_MS)
  try {
    const resp = await fetch(`${apiBase}/desktop/update-manifest`, { signal: controller.signal })
    if (!resp.ok) return null
    const json = await resp.json().catch(() => ({}))
    const data = (json && json.data) || {}
    return {
      enabled: Boolean(data.enabled),
      feed_url: String(data.feed_url || '').replace(/\/+$/, ''),
    }
  } catch {
    return null
  } finally {
    clearTimeout(timer)
  }
}

function setupUpdater({ onStatus, onError, onProgress } = {}) {
  if (!autoUpdater) return null
  autoUpdater.autoDownload = true
  autoUpdater.autoInstallOnAppQuit = true
  autoUpdater.on('checking-for-update', () =>
    onStatus && onStatus('checking', { manual: manualCheckPending }),
  )
  autoUpdater.on('update-available', (info) => {
    onStatus && onStatus('available', { manual: manualCheckPending, ...pickUpdateInfo(info) })
    manualCheckPending = false
  })
  autoUpdater.on('update-not-available', () => {
    onStatus && onStatus('not-available', { manual: manualCheckPending })
    manualCheckPending = false
  })
  autoUpdater.on('download-progress', (progress) => onProgress && onProgress(progress))
  autoUpdater.on('update-downloaded', (info) => {
    onStatus && onStatus('downloaded', { manual: manualCheckPending, ...pickUpdateInfo(info) })
  })
  autoUpdater.on('error', (err) => {
    onError && onError(err)
    // 失败也要回推给 UI：否则按钮会停在「正在检查」无从知晓结果
    onStatus && onStatus('error', { manual: manualCheckPending })
    manualCheckPending = false
  })
  return autoUpdater
}

async function checkForUpdates({ manual = false } = {}) {
  if (!autoUpdater) return
  // 先问服务端「是否允许推送」：admin 关闭后新版本不会到达任何客户端。
  const manifest = await fetchUpdateManifest()
  if (manifest && manifest.enabled === false) {
    manualCheckPending = false
    return
  }
  // 管理员配置了更新包地址则覆盖打包内置 feed，便于随时切换托管位置。
  if (manifest && manifest.feed_url) {
    try {
      autoUpdater.setFeedURL({ provider: 'generic', url: manifest.feed_url })
    } catch (err) {
      console.warn(`[desktop] set feed url failed: ${err && err.message}`)
    }
  }
  manualCheckPending = manual
  autoUpdater.checkForUpdatesAndNotify().catch((err) => {
    console.warn(`[desktop] check for updates failed: ${err && err.message}`)
    manualCheckPending = false
  })
}

// 启动后延迟检查一次，此后每日巡检。定时器 unref，不阻止进程退出。
// 这是「更新能真正到达用户」的关键：此前 checkForUpdates 只在 IPC 手动触发，
// 用户不主动点就永远不会检查。
function schedulePeriodicChecks() {
  if (!autoUpdater) return
  const startupTimer = setTimeout(() => {
    void checkForUpdates()
  }, STARTUP_CHECK_DELAY_MS)
  if (typeof startupTimer.unref === 'function') startupTimer.unref()
  if (periodicTimer) return
  periodicTimer = setInterval(() => {
    void checkForUpdates()
  }, DAILY_CHECK_INTERVAL_MS)
  if (typeof periodicTimer.unref === 'function') periodicTimer.unref()
}

module.exports = {
  setupUpdater,
  configureUpdater,
  checkForUpdates,
  schedulePeriodicChecks,
  normalizeReleaseNotes,
  fetchUpdateManifest,
  autoUpdater,
}
