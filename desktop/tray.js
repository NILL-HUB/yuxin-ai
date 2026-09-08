const { Tray, Menu, nativeImage } = require('electron')
const path = require('node:path')

function createTray({ onShow, onQuit, getStatus }) {
  const icon = nativeImage.createFromPath(path.join(__dirname, 'tray-icon.png'))
  const tray = new Tray(icon.isEmpty() ? nativeImage.createEmpty() : icon)
  tray.setToolTip('钰心AI')

  const buildMenu = () => {
    const status = (getStatus && getStatus()) || {}
    const runningNames = Object.keys(status).filter((name) => status[name])
    const label = runningNames.length
      ? `本机服务：${runningNames.join('/')} 运行中`
      : '本机服务：未运行'
    return Menu.buildFromTemplate([
      { label: '显示钰心AI', click: onShow },
      { type: 'separator' },
      { label, enabled: false },
      { type: 'separator' },
      { label: '退出', click: onQuit },
    ])
  }

  tray.setContextMenu(buildMenu())
  tray.on('click', onShow)
  return tray
}

module.exports = { createTray }
