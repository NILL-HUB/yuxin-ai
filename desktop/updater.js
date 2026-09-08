const path = require('node:path')

let autoUpdater = null
try {
  ;({ autoUpdater } = require('electron-updater'))
} catch {
  autoUpdater = null
}

function setupUpdater({ onStatus, onError, onProgress } = {}) {
  if (!autoUpdater) return null
  autoUpdater.autoDownload = true
  autoUpdater.autoInstallOnAppQuit = true
  autoUpdater.on('checking-for-update', () => onStatus && onStatus('checking'))
  autoUpdater.on('update-available', () => onStatus && onStatus('available'))
  autoUpdater.on('update-not-available', () => onStatus && onStatus('not-available'))
  autoUpdater.on('download-progress', (progress) => onProgress && onProgress(progress))
  autoUpdater.on('update-downloaded', () => onStatus && onStatus('downloaded'))
  autoUpdater.on('error', (err) => onError && onError(err))
  return autoUpdater
}

function checkForUpdates() {
  if (autoUpdater) {
    autoUpdater.checkForUpdatesAndNotify().catch((err) => {
      console.warn(`[desktop] check for updates failed: ${err && err.message}`)
    })
  }
}

module.exports = { setupUpdater, checkForUpdates, autoUpdater }
