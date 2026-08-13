const { contextBridge, ipcRenderer } = require('electron')

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
})
