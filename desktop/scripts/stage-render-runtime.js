// 把渲染运行时暂存到 desktop/vendor/render-runtime/，供 electron-builder
// extraResources 打进安装包。随包分发以彻底避免运行时下载（见 plan §0.5.2）。
//
// 需要暂存的内容：
//   1. node_modules/（**含 onnxruntime-node**，供图片处理/抠像使用）
//   2. Chromium（chrome-headless-shell）
//   3. ffmpeg + ffprobe
//
// onnxruntime-node 裁剪：其 bin/napi-v3/ 带 6 个平台共 536MB，但 dist/binding.js
// 是按 process.platform/arch 动态 require 的，故只保留 win32/ 即可：
//   536MB → 68MB（仅 win32 全 arch）
//
// ⚠️ **平台原生包必须换成 win32 构建（实测会硬崩，勿删此逻辑）**：
//   容器内的 node_modules 只有 linux 平台原生包——
//     @esbuild/linux-x64、@img/sharp-linux-x64、@img/sharp-libvips-linux-x64
//   而 hyperframes 的 dist/cli.js 在**启动阶段就 eagerly import 'sharp'**。
//   若直接打进安装包，Windows 上连 `hyperframes --version` 都会崩：
//     Error: Could not load the "sharp" module using the win32-x64 runtime
//   （onnxruntime 不受影响：它走 N-API v3 多平台布局，一份即可跨平台。）
//   故本脚本会把 @esbuild / @img 下的非目标平台目录裁掉，并从 Windows 侧安装
//   （RENDER_RUNTIME_WIN32_MODULES_DIR）覆盖同版本的 win32 平台包。
//
// 体积参考：node_modules 约 198MB（含裁剪后的 onnxruntime），Chromium 约 338MB。
// 安装包增量约 175–215MB。
//
// 源缺失时打印提示并跳过（不阻断打包），与 stage-cua-driver.js 行为一致。

const fs = require('node:fs')
const path = require('node:path')

// electron-builder 目标平台（本方案当前只出 Windows 包）
const TARGET_PLATFORM = process.env.TARGET_PLATFORM || 'win32'

// onnxruntime-node 跨平台裁剪：仅保留目标平台（默认 win32）
const TARGET_ORT_PLATFORMS = (process.env.ORT_PLATFORMS || 'win32')
  .split(',')
  .map((s) => s.trim())
  .filter(Boolean)

// 含平台原生二进制的包前缀：这些包名形如 <scope>/<name>-<platform>-<arch>
const PLATFORM_SCOPES = ['@esbuild', '@img']

// 必须存在 win32 构建、否则 Windows 上无法启动的原生包（sharp 为 eager import）
const REQUIRED_WIN32_PACKAGES = [
  ['@esbuild', 'win32-x64'],
  ['@img', 'sharp-win32-x64'],
]

function copyDir(src, dest, { skipNames } = {}) {
  fs.mkdirSync(dest, { recursive: true })
  let count = 0
  for (const entry of fs.readdirSync(src, { withFileTypes: true })) {
    if (skipNames && skipNames.has(entry.name)) continue
    const from = path.join(src, entry.name)
    const to = path.join(dest, entry.name)
    if (entry.isDirectory()) {
      count += copyDir(from, to, { skipNames })
    } else if (entry.isFile()) {
      fs.copyFileSync(from, to)
      count += 1
    }
  }
  return count
}

function pruneOnnxPlatforms(ortDir) {
  const napiDir = path.join(ortDir, 'bin', 'napi-v3')
  if (!fs.existsSync(napiDir)) return
  for (const entry of fs.readdirSync(napiDir, { withFileTypes: true })) {
    if (!entry.isDirectory()) continue
    if (!TARGET_ORT_PLATFORMS.includes(entry.name)) {
      fs.rmSync(path.join(napiDir, entry.name), { recursive: true, force: true })
      console.log(`[stage-render-runtime] 裁剪 onnxruntime 平台目录: ${entry.name}`)
    }
  }
}

// 裁掉 @esbuild / @img 下非目标平台的原生包目录。
// 包名形如 `linux-x64` / `sharp-linux-x64` / `sharp-libvips-linux-x64`，
// 平台 token 一定是 `-` 分段中的一段，故按分段判定（不能只看前缀，
// 否则漏掉 `sharp-libvips-linux-x64` 这类中间带平台的包）。
const KNOWN_PLATFORMS = [
  'linux',
  'linuxmusl',
  'darwin',
  'win32',
  'freebsd',
  'android',
  'openbsd',
  'sunos',
  'aix',
  'netbsd',
  'wasm32',
  'webcontainers',
]

function _isForeignPlatformDir(name) {
  const platforms = name
    .split('-')
    .filter((segment) => KNOWN_PLATFORMS.includes(segment))
  // 无平台分段（如 @img/colour）＝ 跨平台包，保留
  if (platforms.length === 0) return false
  return !platforms.includes(TARGET_PLATFORM)
}

function pruneForeignPlatformPackages(nodeModulesDir) {
  for (const scope of PLATFORM_SCOPES) {
    const scopeDir = path.join(nodeModulesDir, scope)
    if (!fs.existsSync(scopeDir)) continue
    for (const entry of fs.readdirSync(scopeDir, { withFileTypes: true })) {
      if (!entry.isDirectory()) continue
      if (_isForeignPlatformDir(entry.name)) {
        fs.rmSync(path.join(scopeDir, entry.name), { recursive: true, force: true })
        console.log(`[stage-render-runtime] 裁剪非目标平台原生包: ${scope}/${entry.name}`)
      }
    }
  }
}

// 从 Windows 侧安装的同版本 hyperframes 依赖树里，overlay 目标平台原生包。
// 容器只有 linux 构建，必须补齐 win32 构建，否则 sharp 在启动阶段硬崩。
function overlayWin32Packages(nodeModulesDir, win32ModulesDir) {
  if (!win32ModulesDir || !fs.existsSync(win32ModulesDir)) {
    throw new Error(
      '缺少 Windows 侧原生包目录（RENDER_RUNTIME_WIN32_MODULES_DIR）。' +
        '容器内只有 linux 原生包（@esbuild/linux-x64、@img/sharp-linux-x64），' +
        '直接打进安装包会导致 Windows 上 hyperframes 启动即崩。' +
        '请在 Windows 上执行 `npm install hyperframes@<同版本>` 后把其 node_modules 路径传入。',
    )
  }
  for (const [scope, pkgName] of REQUIRED_WIN32_PACKAGES) {
    const from = path.join(win32ModulesDir, scope, pkgName)
    if (!fs.existsSync(from)) {
      throw new Error(`Windows 侧缺少原生包：${scope}/${pkgName}（来自 ${win32ModulesDir}）`)
    }
    const to = path.join(nodeModulesDir, scope, pkgName)
    fs.rmSync(to, { recursive: true, force: true })
    copyDir(from, to)
    console.log(`[stage-render-runtime] overlay 目标平台原生包: ${scope}/${pkgName}`)
  }
}

function _assertWin32Packages(nodeModulesDir) {
  const missing = []
  for (const [scope, pkgName] of REQUIRED_WIN32_PACKAGES) {
    if (!fs.existsSync(path.join(nodeModulesDir, scope, pkgName))) {
      missing.push(`${scope}/${pkgName}`)
    }
  }
  if (missing.length) {
    throw new Error(
      '[stage-render-runtime] 暂存结果缺少 Windows 原生包：' +
        missing.join('、') +
        '。\n容器内 node_modules 只有 linux 原生包（@esbuild/linux-x64、' +
        '@img/sharp-linux-x64），而 hyperframes 启动阶段即 import sharp，' +
        '缺失会让安装版连 `hyperframes --version` 都崩。\n' +
        '请在 Windows 上执行 `npm install hyperframes@<与容器同版本>`，' +
        '再用 RENDER_RUNTIME_WIN32_MODULES_DIR=<该 node_modules 路径> 重跑本脚本。',
    )
  }
}

function main() {
  const sourceDir = process.env.RENDER_RUNTIME_SOURCE_DIR || ''
  const win32ModulesDir = process.env.RENDER_RUNTIME_WIN32_MODULES_DIR || ''
  const targetDir =
    process.env.STAGE_TARGET_DIR || path.join(__dirname, '..', 'vendor', 'render-runtime')

  // 目录必须始终存在，否则 electron-builder 的 extraResources 会因源缺失而失败
  fs.mkdirSync(targetDir, { recursive: true })

  if (TARGET_PLATFORM !== 'win32') {
    throw new Error(
      `[stage-render-runtime] 目前仅支持 TARGET_PLATFORM=win32（收到 ${TARGET_PLATFORM}）：` +
        '平台原生包 overlay 清单是按 win32 写定的。',
    )
  }

  if (!sourceDir || !fs.existsSync(sourceDir)) {
    console.warn(
      '[stage-render-runtime] 未找到渲染运行时源目录（RENDER_RUNTIME_SOURCE_DIR）；' +
        '跳过捆绑，本机渲染将不可用（云端回退仍可用）。',
    )
    return
  }

  const nodeModules = path.join(sourceDir, 'node_modules')
  if (!fs.existsSync(nodeModules)) {
    console.warn(`[stage-render-runtime] ${sourceDir} 内无 node_modules，跳过`)
    return
  }

  const stagedModules = path.join(targetDir, 'node_modules')
  const copied = copyDir(nodeModules, stagedModules)
  console.log(`[stage-render-runtime] node_modules 已暂存（${copied} 个文件，含 onnxruntime-node）`)

  // 裁剪 onnxruntime 的非目标平台目录（536MB → 68MB）
  pruneOnnxPlatforms(path.join(stagedModules, 'onnxruntime-node'))

  // 裁掉 @esbuild / @img 下的 linux-only 原生包（容器来源必然只有 linux 构建）
  pruneForeignPlatformPackages(stagedModules)

  // 用 Windows 侧同版本原生包补齐（否则 sharp 启动即崩）
  if (win32ModulesDir) {
    overlayWin32Packages(stagedModules, win32ModulesDir)
  }

  // 最后自校验：宁可打包失败，也不要交付一个「渲染必崩」的安装包
  _assertWin32Packages(stagedModules)

  for (const name of ['chrome-headless-shell', 'chrome-headless-shell.exe', 'ffmpeg', 'ffmpeg.exe', 'ffprobe', 'ffprobe.exe']) {
    const src = path.join(sourceDir, name)
    if (fs.existsSync(src)) {
      fs.copyFileSync(src, path.join(targetDir, name))
      console.log(`[stage-render-runtime] copied ${name}`)
    }
  }

  fs.writeFileSync(
    path.join(targetDir, 'SOURCE.txt'),
    `Staged from ${sourceDir}\nhyperframes + Chromium + ffmpeg/ffprobe + onnxruntime-node\n` +
      `onnxruntime platforms kept: ${TARGET_ORT_PLATFORMS.join(',')}\n` +
      `target platform: ${TARGET_PLATFORM} (win32 native packages overlaid)\n`,
    'utf-8',
  )
  console.log(`[stage-render-runtime] done → ${targetDir}`)
}

main()
