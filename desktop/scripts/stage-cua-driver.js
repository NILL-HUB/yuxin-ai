// 把已安装的 cua-driver 二进制复制到 desktop/vendor/cua-driver/，
// 供 electron-builder extraResources 打进安装包。
//
// cua-driver 采用 packages/releases/<ver>/ 布局，并把 current 作为 junction 指向当前版本。
// 本脚本解析 current（或取最新 release），复制 cua-driver.exe / cua-driver-uia.exe 等文件。
// 未安装时打印提示并跳过（不阻断打包，运行时回退前台 pyautogui 模式）。

const fs = require('node:fs')
const path = require('node:path')
const os = require('node:os')

const BINARIES = ['cua-driver.exe', 'cua-driver-uia.exe', 'cua-cursor-theme.exe']

function resolveInstallRoot() {
  const home = process.env.USERPROFILE || process.env.HOME || os.homedir()
  const packagesDir = path.join(home, '.cua-driver', 'packages')
  if (!fs.existsSync(packagesDir)) return ''

  const current = path.join(packagesDir, 'current')
  try {
    if (fs.existsSync(path.join(current, 'cua-driver.exe'))) return current
  } catch {
    // junction 解析失败继续尝试 releases
  }

  const releasesDir = path.join(packagesDir, 'releases')
  if (!fs.existsSync(releasesDir)) return ''
  const entries = fs
    .readdirSync(releasesDir)
    .filter((name) => fs.existsSync(path.join(releasesDir, name, 'cua-driver.exe')))
    .sort()
  if (!entries.length) return ''
  return path.join(releasesDir, entries[entries.length - 1])
}

function main() {
  const sourceDir = resolveInstallRoot()
  const targetDir = path.join(__dirname, '..', 'vendor', 'cua-driver')

  // 目录必须始终存在，否则 electron-builder 的 extraResources 会因源缺失而失败。
  fs.mkdirSync(targetDir, { recursive: true })

  if (!sourceDir) {
    console.warn(
      '[stage-cua-driver] 未找到 cua-driver 安装（~/.cua-driver/packages）；' +
        '跳过捆绑，运行时将回退前台 pyautogui 模式。',
    )
    return
  }

  let copied = 0
  for (const name of BINARIES) {
    const src = path.join(sourceDir, name)
    if (!fs.existsSync(src)) continue
    fs.copyFileSync(src, path.join(targetDir, name))
    copied += 1
    console.log(`[stage-cua-driver] copied ${name}`)
  }
  if (copied === 0) {
    console.warn(`[stage-cua-driver] ${sourceDir} 内未找到可执行文件，跳过`)
    return
  }
  fs.writeFileSync(
    path.join(targetDir, 'SOURCE.txt'),
    `Staged from ${sourceDir}\ncua-driver (MIT) — https://github.com/trycua/cua\n`,
    'utf-8',
  )
  console.log(`[stage-cua-driver] done → ${targetDir}（${copied} 个文件）`)
}

main()
