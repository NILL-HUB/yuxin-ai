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
  getDesktopConfig: () => ipcRenderer.invoke('desktop:get-config'),
  getCredential: () => ipcRenderer.invoke('desktop:get-credential'),
  setCredential: (token) => ipcRenderer.invoke('desktop:set-credential', token),
  clearCredential: () => ipcRenderer.invoke('desktop:clear-credential'),
  getWorkerVersions: () => ipcRenderer.invoke('desktop:worker-versions'),
  setLaunchAtLogin: (enabled) => ipcRenderer.invoke('desktop:set-launch-at-login', enabled),
  getLaunchAtLogin: () => ipcRenderer.invoke('desktop:get-launch-at-login'),
  checkForUpdates: () => ipcRenderer.invoke('desktop:check-for-updates'),
})
