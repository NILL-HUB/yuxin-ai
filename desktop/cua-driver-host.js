const fs = require('node:fs')
const path = require('node:path')
const { spawn } = require('node:child_process')

// cua-driver 后台计算机控制：桌面端主进程托管常驻 daemon（`serve`），
// worker 侧经 `cua-driver call <tool>` 走命名管道访问。
// 未找到二进制时不报错、不阻断启动，仅标记不可用，worker 侧自动回退 pyautogui。

const STATUS_READY_TIMEOUT_MS = 15000
const STATUS_POLL_INTERVAL_MS = 400

let daemonProcess = null
let daemonAvailable = false
let daemonExePath = ''
let starting = false

function resolveCuaDriverExe({ resourcesDir = process.resourcesPath || '' } = {}) {
  const explicit = String(process.env.CUA_DRIVER_EXE || '').trim()
  if (explicit && fs.existsSync(explicit)) return explicit

  const candidates = []
  // 安装包捆绑位置（extraResources/cua-driver/）
  if (resourcesDir) {
    candidates.push(path.join(resourcesDir, 'cua-driver', 'cua-driver.exe'))
    candidates.push(path.join(resourcesDir, 'cua-driver.exe'))
  }
  // 桌面端用户数据目录（首次运行下载/复制放置）
  const home = process.env.USERPROFILE || process.env.HOME || ''
  if (home) {
    candidates.push(path.join(home, '.cua-driver', 'packages', 'current', 'cua-driver.exe'))
    const releasesDir = path.join(home, '.cua-driver', 'packages', 'releases')
    if (fs.existsSync(releasesDir)) {
      try {
        for (const entry of fs.readdirSync(releasesDir)) {
          candidates.push(path.join(releasesDir, entry, 'cua-driver.exe'))
        }
      } catch {
        // 忽略目录读取失败
      }
    }
  }
  const localAppData = process.env.LOCALAPPDATA || ''
  if (localAppData) {
    candidates.push(
      path.join(localAppData, 'Programs', 'Cua', 'cua-driver', 'bin', 'cua-driver.exe'),
    )
  }
  for (const candidate of candidates) {
    if (candidate && fs.existsSync(candidate)) return candidate
  }
  return ''
}

async function probeDaemon(exePath, timeoutMs = 4000) {
  if (!exePath) return false
  return new Promise((resolve) => {
    const child = spawn(exePath, ['status'], { stdio: ['ignore', 'pipe', 'pipe'] })
    let out = ''
    const timer = setTimeout(() => {
      try {
        child.kill()
      } catch {
        /* ignore */
      }
      resolve(false)
    }, timeoutMs)
    child.stdout.on('data', (chunk) => {
      out += String(chunk)
    })
    child.on('error', () => {
      clearTimeout(timer)
      resolve(false)
    })
    child.on('exit', (code) => {
      clearTimeout(timer)
      resolve(code === 0 && /is running/i.test(out))
    })
  })
}

async function waitUntilReady(exePath, timeoutMs = STATUS_READY_TIMEOUT_MS) {
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    if (await probeDaemon(exePath)) return true
    await new Promise((resolve) => setTimeout(resolve, STATUS_POLL_INTERVAL_MS))
  }
  return false
}

async function startCuaDriver({ resourcesDir, log = console } = {}) {
  if (starting) return daemonAvailable
  const exePath = resolveCuaDriverExe({ resourcesDir })
  if (!exePath) {
    log.warn('[cua-driver] 未找到 cua-driver 可执行文件，后台计算机控制不可用（回退前台模式）')
    return false
  }
  daemonExePath = exePath

  // 已在运行（可能由 autostart / 上一次会话启动）则直接复用。
  if (await probeDaemon(exePath)) {
    daemonAvailable = true
    log.info('[cua-driver] 复用已运行的 daemon')
    return true
  }

  starting = true
  try {
    daemonProcess = spawn(exePath, ['serve'], {
      stdio: ['ignore', 'pipe', 'pipe'],
      windowsHide: true,
    })
    daemonProcess.stdout.on('data', (chunk) => log.info(`[cua-driver] ${String(chunk).trim()}`))
    daemonProcess.stderr.on('data', (chunk) => log.info(`[cua-driver] ${String(chunk).trim()}`))
    daemonProcess.on('error', (err) => {
      log.warn(`[cua-driver] daemon 启动失败: ${err.message}`)
      daemonProcess = null
      daemonAvailable = false
    })
    daemonProcess.on('exit', (code) => {
      log.info(`[cua-driver] daemon exited: ${code}`)
      daemonProcess = null
      daemonAvailable = false
    })
    daemonAvailable = await waitUntilReady(exePath)
    return daemonAvailable
  } finally {
    starting = false
  }
}

function stopCuaDriver() {
  if (!daemonProcess) return
  const child = daemonProcess
  daemonProcess = null
  daemonAvailable = false
  try {
    child.kill()
  } catch {
    /* ignore */
  }
}

function cuaDriverStatus() {
  return {
    available: daemonAvailable,
    running: Boolean(daemonProcess && !daemonProcess.killed),
    exePath: daemonExePath,
  }
}

module.exports = {
  resolveCuaDriverExe,
  startCuaDriver,
  stopCuaDriver,
  cuaDriverStatus,
}
