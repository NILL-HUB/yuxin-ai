const { contextBridge, ipcRenderer } = require('electron')

let desktopConfig = null
try {
  const syncResult = ipcRenderer.sendSync('desktop:get-config-sync')
  if (syncResult && typeof syncResult === 'object') {
    desktopConfig = syncResult
  }
} catch {
  desktopConfig = null
}
contextBridge.exposeInMainWorld('__DESKTOP_CONFIG__', desktopConfig)

contextBridge.exposeInMainWorld('yuxinDesktop', {
  workersStatus: () => ipcRenderer.invoke('workers:status'),
  recycleList: (payload) => ipcRenderer.invoke('recycle:list', payload),
  recycleRestore: (payload) => ipcRenderer.invoke('recycle:restore', payload),
  browserAction: (payload) => ipcRenderer.invoke('browser:action', payload),
  computerControl: (payload) => ipcRenderer.invoke('computer:control', payload),
  wakeStatus: () => ipcRenderer.invoke('wake:status'),
  wakeEnable: () => ipcRenderer.invoke('wake:enable'),
  wakeDisable: () => ipcRenderer.invoke('wake:disable'),
  openExternal: (url) => ipcRenderer.invoke('shell:openExternal', url),
  onDesktopConfigChanged: (callback) => {
    if (typeof callback !== 'function') return () => {}
    const listener = (_event, config) => callback(config)
    ipcRenderer.on('desktop:config-changed', listener)
    return () => ipcRenderer.removeListener('desktop:config-changed', listener)
  },
  getDesktopConfig: () => ipcRenderer.invoke('desktop:get-config'),
  getCredential: () => ipcRenderer.invoke('desktop:get-credential'),
  setCredential: (token) => ipcRenderer.invoke('desktop:set-credential', token),
  clearCredential: () => ipcRenderer.invoke('desktop:clear-credential'),
  getWorkerVersions: () => ipcRenderer.invoke('desktop:worker-versions'),
  setLaunchAtLogin: (enabled) => ipcRenderer.invoke('desktop:set-launch-at-login', enabled),
  getLaunchAtLogin: () => ipcRenderer.invoke('desktop:get-launch-at-login'),
  checkForUpdates: () => ipcRenderer.invoke('desktop:check-for-updates'),
})

// 自绘标题栏窗口控制（titleBarStyle:hidden + titleBarOverlay 方案）
contextBridge.exposeInMainWorld('windowControls', {
  minimize: () => ipcRenderer.send('window:minimize'),
  toggleMaximize: () => ipcRenderer.send('window:toggle-maximize'),
  close: () => ipcRenderer.send('window:close'),
  isMaximized: () => ipcRenderer.invoke('window:is-maximized'),
  getOverlayState: () => ipcRenderer.invoke('window:get-overlay-state'),
  onMaximizedChanged: (callback) => {
    if (typeof callback !== 'function') return () => {}
    const listener = (_event, isMaximized) => callback(isMaximized)
    ipcRenderer.on('window:maximized-changed', listener)
    return () => ipcRenderer.removeListener('window:maximized-changed', listener)
  },
})
