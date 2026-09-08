const { app, BrowserWindow, ipcMain, shell, safeStorage, Notification, session, Menu, screen } = require('electron')
const { spawn, execSync } = require('child_process')
const net = require('net')
const crypto = require('crypto')
const path = require('path')
const fs = require('fs')
const { createBridge } = require('./bridge')
const { loadServerConfig, DEFAULT_ENTRY_ORIGIN } = require('./server-config')
const { createCredentialStore } = require('./credential-store')
const { createTray } = require('./tray')
const { setupUpdater, checkForUpdates, autoUpdater } = require('./updater')
const { computeWindowOptions, loadState, saveState } = require('./window-state')

let mainWindow = null
let workers = new Map()
let bridgeServer = null
let tray = null
let isQuitting = false

let credentialStore = null
let desktopRuntimeConfig = null
let desktopConfigCache = null
let serverConfigCachePath = null
let serverConfigRefreshing = false
let windowStateFilePath = null

function randomToken() {
  return crypto.randomBytes(24).toString('hex')
}

function pythonBin() {
  return process.env.DESKTOP_PYTHON || 'python'
}

function workerScript() {
  // dev 模式（无打包 exe）统一走 worker_super：与打包版同一入口，
  // 保证宿主存活看门狗（YUXIN_HOST_PID）在开发环境同样生效。
  const apiDir = path.resolve(__dirname, '..', 'api')
  return path.join(apiDir, 'scripts', 'worker_super.py')
}

function notify(title, body) {
  try {
    if (Notification.isSupported()) {
      new Notification({ title, body }).show()
    }
  } catch (err) {
    console.warn(`[desktop] notification failed: ${err.message}`)
  }
}

function showMainWindow() {
  if (!mainWindow) return
  if (mainWindow.isMinimized()) mainWindow.restore()
  mainWindow.show()
  mainWindow.focus()
}

function workerStatusSnapshot() {
  const result = {}
  for (const [name, child] of workers.entries()) {
    result[name] = Boolean(child && !child.killed)
  }
  return result
}

// 为 worker 探测一个空闲端口：优先使用 preferred，被占用则向上顺延。
// 桌面端与 Docker 容器可能同用 8765-8767（docker-compose 映射），
// 顺延可避免绑定失败（WinError 10013）导致 worker 异常退出。
// exclude 用于串行分配时跳过已被其它 worker 拿到的端口，避免撞端口。
async function probePort(preferred, maxAttempts = 50, exclude = new Set()) {
  for (let offset = 0; offset < maxAttempts; offset += 1) {
    const candidate = preferred + offset
    if (exclude.has(candidate)) continue
    try {
      const server = net.createServer()
      const ok = await new Promise((resolve) => {
        server.once('error', () => resolve(false))
        server.listen(candidate, '127.0.0.1', () => {
          server.close(() => resolve(true))
        })
      })
      if (ok) return candidate
    } catch {
      // 继续尝试下一个
    }
  }
  return preferred
}

function workerCommand(name) {
  const resourcesDir = process.resourcesPath || ''
  const bundledCandidates = [
    path.join(resourcesDir, 'yuxin-worker', 'yuxin-worker.exe'),
    path.join(resourcesDir, 'yuxin-worker.exe'),
  ]
  for (const exePath of bundledCandidates) {
    if (exePath && fs.existsSync(exePath)) {
      return { cmd: exePath, args: [name] }
    }
  }
  const script = workerScript()
  if (script && fs.existsSync(script)) {
    return { cmd: pythonBin(), args: [script, name] }
  }
  return null
}

function startWorker(name, env) {
  const command = workerCommand(name)
  if (!command) {
    console.warn(`[desktop] worker 命令不可用: ${name}（无打包 exe，脚本 ${workerScript(name)} 也不存在）`)
    return
  }
  const child = spawn(command.cmd, command.args, {
    env: {
      ...process.env,
      ...env,
      // 宿主存活看门狗：worker 周期性检测 Electron 主进程 PID，
      // 主进程退出（正常/被杀/崩溃）即自杀，避免进程树残留。
      YUXIN_HOST_PID: String(process.pid),
    },
    stdio: ['ignore', 'pipe', 'pipe'],
  })
  child.stdout.on('data', (chunk) => console.log(`[${name}] ${String(chunk).trim()}`))
  child.stderr.on('data', (chunk) => console.error(`[${name}] ${String(chunk).trim()}`))
  child.on('error', (err) => {
    console.error(`[desktop] ${name} worker spawn failed: ${err.message}`)
    workers.delete(name)
  })
  child.on('exit', (code) => {
    console.log(`[desktop] ${name} worker exited: ${code}`)
    workers.delete(name)
    if (!isQuitting) {
      notify(`${name} worker 已退出`, code ? `异常退出（code ${code}），功能可能不可用` : '已停止运行')
    }
  })
  workers.set(name, child)
  console.log(`[desktop] started ${name} worker (cmd=${command.cmd} pid=${child.pid})`)
}

function stopWorker(name) {
  const child = workers.get(name)
  if (!child) return
  workers.delete(name)
  // Windows 下 worker 为 PyInstaller onefile：spawn 出来的是引导进程，
  // 它会再派生真正的服务进程。child.kill() 只杀引导进程，服务进程会变孤儿
  // 残留并继续占用端口 → 用 taskkill /T 杀整棵进程树。
  if (process.platform === 'win32' && child.pid) {
    try {
      execSync(`taskkill /PID ${child.pid} /T /F`, { stdio: 'ignore' })
      return
    } catch {
      // taskkill 失败（进程已退出等）时回退 child.kill()
    }
  }
  child.kill()
}

async function callLocalWorker(baseUrl, token, payload) {
  const response = await fetch(`${baseUrl}`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify(payload),
  })
  return response.json()
}

function toDesktopConfig(serverCfg) {
  const serverCfgSafe = serverCfg || {}
  const origin = String(serverCfgSafe.api_origin || '').replace(/\/+$/, '')
  const prefixRaw = String(serverCfgSafe.api_prefix || '/api')
  const prefix = (prefixRaw.startsWith('/') ? prefixRaw : `/${prefixRaw}`).replace(/\/+$/, '') || '/api'
  return {
    apiBase: `${origin}${prefix}`,
    apiOrigin: origin,
    socketUrl: origin,
    socketPath: `${prefix}/socket.io`,
    appName: serverCfgSafe.app_name || '钰心AI',
  }
}

function resolveCorsOrigin() {
  // renderer 加载自 file://（Origin: null），请求远程 API 属跨域；
  // 浏览器 CORS 会把响应拦掉。此处对已配置的 API origin 放宽 CORS 响应头。
  const cache = desktopConfigCache || (readDiskConfigCache() ? toDesktopConfig(readDiskConfigCache()) : null)
  return cache ? cache.apiOrigin : null
}

function readDiskConfigCache() {
  if (!serverConfigCachePath || !fs.existsSync(serverConfigCachePath)) return null
  try {
    const raw = JSON.parse(fs.readFileSync(serverConfigCachePath, 'utf-8'))
    if (raw && raw.api_origin) return raw
  } catch {
    // 缓存损坏忽略
  }
  return null
}

function applyServerConfig(serverCfg) {
  desktopRuntimeConfig = serverCfg
  desktopConfigCache = toDesktopConfig(serverCfg)
}

function broadcastConfig(config) {
  // contextBridge 注入的 window.__DESKTOP_CONFIG__ 是启动时只读快照，主进程无法直写；
  // 运行中刷新到的新配置通过该事件下发，renderer 用 preload 暴露的
  // onDesktopConfigChanged(callback) 订阅（返回取消函数）。
  for (const win of BrowserWindow.getAllWindows()) {
    win.webContents.send('desktop:config-changed', config)
  }
}

async function refreshServerConfig() {
  if (!serverConfigCachePath || serverConfigRefreshing) return
  serverConfigRefreshing = true
  try {
    const cfg = await loadServerConfig({
      entryOrigin: DEFAULT_ENTRY_ORIGIN,
      cachePath: serverConfigCachePath,
    })
    const next = toDesktopConfig(cfg)
    const prev = desktopConfigCache
    applyServerConfig(cfg)
    if (!prev || JSON.stringify(prev) !== JSON.stringify(next)) {
      broadcastConfig(next)
      const changedOrigin = prev && prev.apiOrigin !== next.apiOrigin
      if (changedOrigin) {
        console.warn(
          `[desktop] server config updated: api_origin changed from ${prev.apiOrigin} to ${next.apiOrigin}; ` +
            'renderer 已订阅 desktop:config-changed，若未热生效请重启应用',
        )
      }
    }
  } catch (err) {
    console.warn(`[desktop] refresh server config failed: ${err.message}`)
  } finally {
    serverConfigRefreshing = false
  }
}

function syncConfig() {
  if (!desktopConfigCache) {
    const serverCfg = readDiskConfigCache() || {
      api_origin: DEFAULT_ENTRY_ORIGIN,
      api_prefix: '/api',
      app_name: '钰心AI',
    }
    applyServerConfig(serverCfg)
    void refreshServerConfig()
  }
  return desktopConfigCache
}

function broadcastWindowState() {
  if (!mainWindow || mainWindow.isDestroyed()) return
  for (const win of BrowserWindow.getAllWindows()) {
    if (!win.isDestroyed()) {
      win.webContents.send('window:maximized-changed', mainWindow.isMaximized())
    }
  }
}

function createWindow() {
  const savedState = loadState(windowStateFilePath)
  const options = computeWindowOptions(savedState, screen.getAllDisplays())

  mainWindow = new BrowserWindow({
    ...options,
    minWidth: 940,
    minHeight: 620,
    title: '钰心AI',
    show: false,
    // 原生窗口外观：去掉系统标题栏改用自绘标题栏（拖拽区在 renderer），
    // Windows 保留系统 min/max/close 按钮作为 titleBarOverlay（Hermes 同款方案）。
    titleBarStyle: 'hidden',
    ...(process.platform === 'win32'
      ? { titleBarOverlay: { color: '#00000000', symbolColor: '#4b5563', height: 44 } }
      : {}),
    backgroundColor: '#f7f7f7',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  })

  if (savedState && savedState.isMaximized) {
    mainWindow.maximize()
  }

  mainWindow.on('ready-to-show', () => {
    mainWindow.show()
  })
  mainWindow.on('maximize', broadcastWindowState)
  mainWindow.on('unmaximize', broadcastWindowState)
  mainWindow.on('close', (event) => {
    if (!isQuitting) {
      event.preventDefault()
      saveState(windowStateFilePath, mainWindow)
      mainWindow.hide()
    } else {
      saveState(windowStateFilePath, mainWindow)
    }
  })
  mainWindow.on('closed', () => {
    mainWindow = null
  })
  const devUrl = process.env.VITE_DEV_SERVER_URL
  if (devUrl) {
    mainWindow.loadURL(devUrl)
  } else {
    mainWindow.loadFile(resolveUiIndex())
  }
}

// 打包模式 UI 经 extraResources 落到 resources/ui-dist；开发模式回退源码 ui/dist。
function resolveUiIndex() {
  const packaged = path.join(process.resourcesPath || '', 'ui-dist', 'index.html')
  if (fs.existsSync(packaged)) {
    return packaged
  }
  return path.join(__dirname, '..', 'ui', 'dist', 'index.html')
}

app.whenReady().then(async () => {
  // 移除默认应用菜单栏（File/Edit/View...），呈现原生客户端外观
  Menu.setApplicationMenu(null)

  credentialStore = createCredentialStore({
    filePath: path.join(app.getPath('userData'), 'credential.bin'),
    safeStorage: safeStorage.isEncryptionAvailable() ? safeStorage : null,
  })
  serverConfigCachePath = path.join(app.getPath('userData'), 'server-config.json')
  windowStateFilePath = path.join(app.getPath('userData'), 'window-state.json')

  // renderer 以 file:// 加载（Origin: null），对配置的 API origin 放宽 CORS，
  // 使登录/业务请求不被浏览器同源策略拦截。
  session.defaultSession.webRequest.onHeadersReceived((details, callback) => {
    const apiOrigin = resolveCorsOrigin()
    const requestUrl = details.url || ''
    const matchesApi = apiOrigin && requestUrl.toLowerCase().startsWith(apiOrigin.toLowerCase())
    const responseHeaders = { ...details.responseHeaders }
    if (matchesApi) {
      responseHeaders['Access-Control-Allow-Origin'] = ['*']
      responseHeaders['Access-Control-Allow-Credentials'] = ['true']
      responseHeaders['Access-Control-Allow-Headers'] = ['Content-Type, Authorization, X-Account-Id']
      responseHeaders['Access-Control-Allow-Methods'] = ['GET, POST, PUT, PATCH, DELETE, OPTIONS']
    }
    if (details.method === 'OPTIONS' && matchesApi) {
      return callback({ responseHeaders, statusLine: 'HTTP/1.1 204 No Content', statusCode: 204 })
    }
    callback({ responseHeaders })
  })

  const tokens = {
    os: randomToken(),
    browser: randomToken(),
    computer: randomToken(),
    wake: randomToken(),
    bridge: randomToken(),
  }

  // 解析 worker 端口：优先环境变量，其次默认值；被占用则自动顺延，
  // 避免与 Docker 容器映射（8766/8767）等冲突导致 worker 绑定失败。
  // 串行探测并互相排除已分配端口，避免两个 worker 顺延到同一端口。
  const preferOsPort = Number(process.env.OS_AUTOMATION_PORT || 8765)
  const preferBrowserPort = Number(process.env.BROWSER_AUTOMATION_PORT || 8766)
  const preferComputerPort = Number(process.env.COMPUTER_CONTROL_PORT || 8767)
  const osPort = await probePort(preferOsPort)
  const browserPort = await probePort(preferBrowserPort, 50, new Set([osPort]))
  const computerPort = await probePort(preferComputerPort, 50, new Set([osPort, browserPort]))
  if (osPort !== preferOsPort) {
    console.log(`[desktop] os worker 端口 ${preferOsPort} 被占用，改用 ${osPort}`)
  }
  if (browserPort !== preferBrowserPort) {
    console.log(`[desktop] browser worker 端口 ${preferBrowserPort} 被占用，改用 ${browserPort}`)
  }
  if (computerPort !== preferComputerPort) {
    console.log(`[desktop] computer worker 端口 ${preferComputerPort} 被占用，改用 ${computerPort}`)
  }

  startWorker('os', {
    OS_AUTOMATION_TOKEN: tokens.os,
    OS_AUTOMATION_PORT: String(osPort),
    OS_AUTOMATION_SAFE_ROOT: process.env.OS_AUTOMATION_SAFE_ROOT || '',
  })
  startWorker('browser', {
    BROWSER_AUTOMATION_TOKEN: tokens.browser,
    BROWSER_AUTOMATION_PORT: String(browserPort),
  })
  startWorker('computer', {
    COMPUTER_CONTROL_TOKEN: tokens.computer,
    COMPUTER_CONTROL_PORT: String(computerPort),
  })

  bridgeServer = createBridge({
    token: tokens.bridge,
    filePort: osPort,
    fileToken: tokens.os,
    recyclePort: osPort,
    recycleToken: tokens.os,
    snapshotPort: osPort,
    snapshotToken: tokens.os,
    browserPort,
    browserToken: tokens.browser,
    computerPort,
    computerToken: tokens.computer,
  })
  bridgeServer.listen(Number(process.env.DESKTOP_BRIDGE_PORT || 9876), '127.0.0.1', () => {
    console.log('[desktop] local capability bridge listening on 127.0.0.1:9876')
  })

  ipcMain.on('desktop:get-config-sync', (event) => {
    event.returnValue = syncConfig()
  })
  ipcMain.handle('desktop:get-config', async () => {
    const cached = syncConfig()
    if (!desktopRuntimeConfig || desktopRuntimeConfig.api_origin === DEFAULT_ENTRY_ORIGIN) {
      await refreshServerConfig()
    }
    return desktopConfigCache || cached
  })
  ipcMain.handle('desktop:get-credential', () => (credentialStore ? credentialStore.load() : null))
  ipcMain.handle('desktop:set-credential', (_event, token) => {
    if (credentialStore && typeof token === 'string' && token) {
      return credentialStore.save(token)
    }
    return false
  })
  ipcMain.handle('desktop:clear-credential', () => {
    if (credentialStore) credentialStore.clear()
    return true
  })
  ipcMain.handle('desktop:worker-versions', () => {
    const result = {}
    for (const [name, child] of workers.entries()) {
      result[name] = { running: Boolean(child && !child.killed), pid: child.pid, version: null }
    }
    return result
  })
  ipcMain.handle('desktop:set-launch-at-login', (_event, enabled) => {
    app.setLoginItemSettings({ openAtLogin: Boolean(enabled) })
    return true
  })
  ipcMain.handle('desktop:get-launch-at-login', () => app.getLoginItemSettings().openAtLogin)
  ipcMain.handle('desktop:check-for-updates', () => {
    if (!autoUpdater) {
      return { ok: false, reason: 'updater_disabled' }
    }
    checkForUpdates()
    return { ok: true }
  })

  ipcMain.handle('workers:status', () => {
    const result = {}
    for (const [name, child] of workers.entries()) {
      result[name] = { running: !child.killed, pid: child.pid }
    }
    return result
  })

  ipcMain.handle('recycle:list', (_event, payload) =>
    callLocalWorker(`http://127.0.0.1:${process.env.OS_AUTOMATION_PORT || '8765'}/recycle`, tokens.os, {
      ...payload,
      op: 'list',
    }),
  )
  ipcMain.handle('recycle:restore', (_event, payload) =>
    callLocalWorker(`http://127.0.0.1:${process.env.OS_AUTOMATION_PORT || '8765'}/recycle`, tokens.os, {
      ...payload,
      op: 'restore',
    }),
  )
  ipcMain.handle('browser:action', (_event, payload) =>
    callLocalWorker(`http://127.0.0.1:${process.env.BROWSER_AUTOMATION_PORT || '8766'}/browser`, tokens.browser, payload),
  )
  ipcMain.handle('computer:control', (_event, payload) =>
    callLocalWorker(`http://127.0.0.1:${process.env.COMPUTER_CONTROL_PORT || '8767'}/control`, tokens.computer, payload),
  )
  ipcMain.handle('wake:status', () => {
    const child = workers.get('wake')
    return { running: Boolean(child && !child.killed) }
  })
  ipcMain.handle('wake:enable', () => {
    if (workers.has('wake') && !workers.get('wake').killed) return true
    startWorker('wake', {
      WAKE_WORD_TOKEN: tokens.wake,
      WAKE_WORD_KEYWORD: process.env.WAKE_WORD_KEYWORD || 'hey yuxin',
      WAKE_WORD_ENDPOINT: process.env.WAKE_WORD_ENDPOINT || '',
    })
    return true
  })
  ipcMain.handle('wake:disable', () => {
    stopWorker('wake')
    return true
  })
  ipcMain.handle('shell:openExternal', (_event, url) => {
    if (typeof url === 'string' && /^https?:\/\//i.test(url)) {
      shell.openExternal(url)
    }
  })

  tray = createTray({
    onShow: showMainWindow,
    onQuit: () => {
      isQuitting = true
      app.quit()
    },
    getStatus: workerStatusSnapshot,
  })

  setupUpdater({
    onStatus: (status) => {
      if (status === 'available') notify('钰心AI 有更新可用', '正在后台下载，完成后将提示安装')
      if (status === 'downloaded') notify('钰心AI 更新已就绪', '重启应用即可完成更新')
      for (const win of BrowserWindow.getAllWindows()) {
        win.webContents.send('desktop:update-status', status)
      }
    },
    onError: (err) => {
      console.warn(`[desktop] updater error: ${err && err.message}`)
    },
  })

  // 自绘标题栏的窗口控制：从 event.sender 反查窗口，不收窗口 id 参数（安全）
  ipcMain.on('window:minimize', (event) => {
    BrowserWindow.fromWebContents(event.sender)?.minimize()
  })
  ipcMain.on('window:toggle-maximize', (event) => {
    const win = BrowserWindow.fromWebContents(event.sender)
    if (!win) return
    if (win.isMaximized()) {
      win.unmaximize()
    } else {
      win.maximize()
    }
  })
  ipcMain.on('window:close', (event) => {
    BrowserWindow.fromWebContents(event.sender)?.close()
  })
  ipcMain.handle('window:is-maximized', (event) => {
    const win = BrowserWindow.fromWebContents(event.sender)
    return Boolean(win && win.isMaximized())
  })
  ipcMain.handle('window:get-overlay-state', () => {
    // 暴露给 renderer：是否启用了 windowControlsOverlay（决定标题栏右侧预留宽度）
    return { overlay: process.platform === 'win32' }
  })

  createWindow()
})

app.on('window-all-closed', () => {
  // 关闭到托盘：窗口全关仍驻留（worker 与桥继续服务），托盘"退出"才真正退出
  if (process.platform !== 'darwin') {
    // 不 quit；仅当无托盘（如初始化异常）时兜底退出
    if (!tray) {
      isQuitting = true
      app.quit()
    }
  }
})

app.on('before-quit', () => {
  isQuitting = true
  for (const name of [...workers.keys()]) stopWorker(name)
  if (bridgeServer) bridgeServer.close()
})
