const { app, BrowserWindow, ipcMain, shell } = require('electron')
const { spawn } = require('child_process')
const crypto = require('crypto')
const path = require('path')
const fs = require('fs')
const { createBridge } = require('./bridge')

let mainWindow = null
let workers = new Map()
let bridgeServer = null

function randomToken() {
  return crypto.randomBytes(24).toString('hex')
}

function pythonBin() {
  return process.env.DESKTOP_PYTHON || 'python'
}

function workerScript(name) {
  const apiDir = path.resolve(__dirname, '..', 'api')
  const scripts = {
    os: path.join(apiDir, 'scripts', 'os_automation_worker.py'),
    browser: path.join(apiDir, 'scripts', 'browser_automation_worker.py'),
    computer: path.join(apiDir, 'scripts', 'computer_control_worker.py'),
    wake: path.join(apiDir, 'scripts', 'wake_word_worker.py'),
  }
  return scripts[name]
}

function startWorker(name, env) {
  const script = workerScript(name)
  if (!fs.existsSync(script)) {
    console.warn(`[desktop] worker 脚本不存在: ${script}`)
    return
  }
  const child = spawn(pythonBin(), [script], {
    env: { ...process.env, ...env },
    stdio: ['ignore', 'pipe', 'pipe'],
  })
  child.stdout.on('data', (chunk) => console.log(`[${name}] ${String(chunk).trim()}`))
  child.stderr.on('data', (chunk) => console.error(`[${name}] ${String(chunk).trim()}`))
  child.on('exit', (code) => {
    console.log(`[desktop] ${name} worker exited: ${code}`)
    workers.delete(name)
  })
  workers.set(name, child)
  console.log(`[desktop] started ${name} worker (pid=${child.pid})`)
}

function stopWorker(name) {
  const child = workers.get(name)
  if (child) {
    child.kill()
    workers.delete(name)
  }
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

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1280,
    height: 860,
    title: '钰心AI',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  })
  const devUrl = process.env.VITE_DEV_SERVER_URL
  if (devUrl) {
    mainWindow.loadURL(devUrl)
  } else {
    mainWindow.loadFile(path.join(__dirname, '..', 'ui', 'dist', 'index.html'))
  }
}

app.whenReady().then(() => {
  const tokens = {
    os: randomToken(),
    browser: randomToken(),
    computer: randomToken(),
    wake: randomToken(),
    bridge: randomToken(),
  }
  startWorker('os', {
    OS_AUTOMATION_TOKEN: tokens.os,
    OS_AUTOMATION_PORT: process.env.OS_AUTOMATION_PORT || '8765',
    OS_AUTOMATION_SAFE_ROOT: process.env.OS_AUTOMATION_SAFE_ROOT || '',
  })
  startWorker('browser', {
    BROWSER_AUTOMATION_TOKEN: tokens.browser,
    BROWSER_AUTOMATION_PORT: process.env.BROWSER_AUTOMATION_PORT || '8766',
  })
  startWorker('computer', {
    COMPUTER_CONTROL_TOKEN: tokens.computer,
    COMPUTER_CONTROL_PORT: process.env.COMPUTER_CONTROL_PORT || '8767',
  })

  bridgeServer = createBridge({
    token: tokens.bridge,
    recyclePort: process.env.OS_AUTOMATION_PORT || '8765',
    browserPort: process.env.BROWSER_AUTOMATION_PORT || '8766',
    computerPort: process.env.COMPUTER_CONTROL_PORT || '8767',
    recycleToken: tokens.os,
    browserToken: tokens.browser,
    computerToken: tokens.computer,
  })
  bridgeServer.listen(Number(process.env.DESKTOP_BRIDGE_PORT || 9876), '127.0.0.1', () => {
    console.log('[desktop] local capability bridge listening on 127.0.0.1:9876')
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

  createWindow()
})

app.on('window-all-closed', () => {
  for (const name of [...workers.keys()]) stopWorker(name)
  if (bridgeServer) bridgeServer.close()
  if (process.platform !== 'darwin') app.quit()
})
