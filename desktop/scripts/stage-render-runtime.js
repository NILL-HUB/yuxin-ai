// 把渲染运行时暂存到 desktop/vendor/render-runtime/，供 electron-builder
// extraResources 打进安装包。随包分发以彻底避免运行时下载（见 plan §0.5.2）。
//
// 需要暂存的内容（四类）：
//   1. node_modules/（含 onnxruntime-node，供图片处理/抠像使用）
//   2. Chromium（chrome-headless-shell **整目录**，不是单文件）
//   3. ffmpeg + ffprobe（**同一构建的自包含版本**）
//
// ── 实测踩坑（均为真机验证，勿删对应逻辑） ────────────────────────────────
//
// [坑 1] node_modules 里的平台原生包不是全平台。
//   容器内只有 @esbuild/linux-x64、@img/sharp-linux-x64、@img/sharp-libvips-linux-x64，
//   而 hyperframes/dist/cli.js 在**启动阶段就 eager import 'sharp'**，直接打包会让
//   Windows 上连 `hyperframes --version` 都崩：
//     Error: Could not load the "sharp" module using the win32-x64 runtime
//   故需裁掉非目标平台包，并从 Windows 侧 overlay 同版本 win32 包
//   （RENDER_RUNTIME_WIN32_MODULES_DIR）。
//   onnxruntime-node 不受影响：它走 N-API v3 多平台布局，一份即跨平台。
//
// [坑 2] Chromium 不是单文件。chrome-headless-shell.exe 依赖同目录的
//   icudtl.dat / *.pak / *.dll，只拷 exe 会在启动时直接崩溃（实测退出码 0x80000003）。
//   故必须整目录复制（RENDER_RUNTIME_BROWSER_DIR）。
//
// [坑 3] ffmpeg 需要三项能力：image2pipe 解复用 + mjpeg 解码 + libx264 编码。
//   实测缺 image2pipe 的构建报 `Unknown input format: 'image2pipe'`；
//   缺 libx264 的构建无法编码。故暂存前做能力探测，不达标**直接报错终止打包**，
//   避免产出一个「点了就失败」的安装包。
//
// 体积参考（2026-09-19 真机实测暂存结果）：合计约 687 MB——
//   node_modules 222 MB（含裁剪后 onnxruntime）+ Chromium 整目录 268 MB
//   + ffmpeg/ffprobe 各约 98 MB（必须是自包含静态构建；容器内那版是动态链接，不能直接用）。
// NSIS 压缩后安装包增量约 220–260 MB。
// 可选瘦身：locales/（42 MB）+ hyphen-data/ 实测非必需（渲染链路不读）。
//
// 源缺失时打印提示并跳过（不阻断打包），与 stage-cua-driver.js 行为一致。

const fs = require('node:fs')
const path = require('node:path')
const { execFileSync } = require('node:child_process')

// electron-builder 目标平台（本方案当前只出 Windows 包）
const TARGET_PLATFORM = process.env.TARGET_PLATFORM || 'win32'

// onnxruntime-node 跨平台裁剪：仅保留目标平台（默认 win32）
const TARGET_ORT_PLATFORMS = (process.env.ORT_PLATFORMS || 'win32')
  .split(',')
  .map((s) => s.trim())
  .filter(Boolean)

// 含平台原生二进制的包前缀：这些包名形如 <scope>/<name>-<platform>-<arch>
const PLATFORM_SCOPES = ['@esbuild', '@img']

// 必须存在目标平台构建、否则无法启动的原生包（sharp 为 eager import）
const REQUIRED_WIN32_PACKAGES = [
  ['@esbuild', 'win32-x64'],
  ['@img', 'sharp-win32-x64'],
]

// 平台 token 全集（用于判定某个包目录是否属于「别的平台」）
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

const _withExe = (name) =>
  TARGET_PLATFORM === 'win32' ? `${name}.exe` : name

const BROWSER_EXE = _withExe('chrome-headless-shell')

// Chromium 启动必需的旁挂文件：缺任一则 exe 起不来（坑 2）
const REQUIRED_BROWSER_FILES = [BROWSER_EXE, 'icudtl.dat']

// ffmpeg 渲染必需能力（坑 3）
const REQUIRED_FFMPEG_FEATURES = [
  { args: ['-hide_banner', '-demuxers'], keyword: 'image2pipe', label: 'image2pipe 解复用器' },
  { args: ['-hide_banner', '-decoders'], keyword: 'mjpeg', label: 'mjpeg 解码器' },
  { args: ['-hide_banner', '-encoders'], keyword: 'libx264', label: 'libx264 编码器' },
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

function _capture(exe, args) {
  return execFileSync(exe, args, { encoding: 'utf-8', stdio: ['ignore', 'pipe', 'pipe'] })
}

/**
 * 探测 ffmpeg 是否具备渲染所需能力（坑 3）。
 * 返回缺失能力的中文描述数组；为空表示通过。
 *
 * run 可注入（便于单测）：签名 (args: string[]) => string（stdout）。
 */
function checkFfmpegCapabilities(ffmpegPath, { run } = {}) {
  const runner = run || ((args) => _capture(ffmpegPath, args))
  const missing = []
  for (const { args, keyword, label } of REQUIRED_FFMPEG_FEATURES) {
    let output = ''
    try {
      output = runner(args)
    } catch (error) {
      missing.push(`${label}（探测失败：${String(error.message).split('\n')[0]}）`)
      continue
    }
    if (!output.includes(keyword)) missing.push(label)
  }
  return missing
}

// 解析传入的浏览器路径：既接受 exe 路径，也接受所在目录
function _resolveBrowserDir(browserDirOrExe) {
  const raw = String(browserDirOrExe || '').trim()
  if (!raw) return ''
  if (raw.toLowerCase().endsWith('.exe') || raw.toLowerCase() === BROWSER_EXE) {
    return path.dirname(raw)
  }
  return raw
}

function stageBrowser(targetDir, browserDirOrExe) {
  const browserDir = _resolveBrowserDir(browserDirOrExe)
  if (!browserDir || !fs.existsSync(browserDir)) {
    throw new Error(
      `[stage-render-runtime] 浏览器目录不存在：${browserDirOrExe}。` +
        '（RENDER_RUNTIME_BROWSER_DIR 应指向含 chrome-headless-shell.exe 的目录）',
    )
  }
  // 坑 2：整目录复制，不可只拷 exe
  const copied = copyDir(browserDir, targetDir)
  const missing = REQUIRED_BROWSER_FILES.filter(
    (name) => !fs.existsSync(path.join(targetDir, name)),
  )
  if (missing.length) {
    throw new Error(
      `[stage-render-runtime] Chromium 暂存不完整，缺少：${missing.join('、')}。\n` +
        'chrome-headless-shell.exe 依赖同目录的 icudtl.dat / *.pak / *.dll，' +
        '只拷单个 exe 会导致浏览器启动即崩（实测 0x80000003）。',
    )
  }
  console.log(`[stage-render-runtime] Chromium 已整目录暂存（${copied} 个文件，含 DLL/pak/icudtl）`)
}

function stageFfmpeg(targetDir, ffmpegPath, ffprobePath, { skipProbe } = {}) {
  for (const [label, src] of [['ffmpeg', ffmpegPath], ['ffprobe', ffprobePath]]) {
    if (!src || !fs.existsSync(src)) {
      throw new Error(
        `[stage-render-runtime] 缺少 ${label}（RENDER_RUNTIME_${label.toUpperCase()}_PATH）：` +
          `${src || '(未设置)'}。需为**自包含**且成对的 Windows 构建。`,
      )
    }
  }
  // 目标名固定为 ffmpeg.exe / ffprobe.exe —— render-runtime.js 按此名解析
  fs.copyFileSync(ffmpegPath, path.join(targetDir, _withExe('ffmpeg')))
  fs.copyFileSync(ffprobePath, path.join(targetDir, _withExe('ffprobe')))

  if (!skipProbe) {
    const missing = checkFfmpegCapabilities(path.join(targetDir, _withExe('ffmpeg')))
    if (missing.length) {
      throw new Error(
        `[stage-render-runtime] ffmpeg 缺少渲染必需能力：${missing.join('、')}。\n` +
          '实测：缺 image2pipe 会报 `Unknown input format: \'image2pipe\'`，' +
          '缺 libx264 无法编码。请换用**自包含的 gyan.dev/BtbN essentials 构建**。',
      )
    }
    console.log('[stage-render-runtime] ffmpeg 能力探测通过（image2pipe / mjpeg / libx264）')
  } else {
    console.warn('[stage-render-runtime] 已跳过 ffmpeg 能力探测（RENDER_RUNTIME_SKIP_BINARY_PROBE=1）')
  }
}

function _safeVersion(exe, args) {
  try {
    return _capture(exe, args).split('\n')[0].trim()
  } catch {
    return ''
  }
}

function main() {
  const sourceDir = process.env.RENDER_RUNTIME_SOURCE_DIR || ''
  const win32ModulesDir = process.env.RENDER_RUNTIME_WIN32_MODULES_DIR || ''
  const browserDirOrExe = process.env.RENDER_RUNTIME_BROWSER_DIR || ''
  const ffmpegPath = process.env.RENDER_RUNTIME_FFMPEG_PATH || ''
  const ffprobePath = process.env.RENDER_RUNTIME_FFPROBE_PATH || ''
  const skipProbe = process.env.RENDER_RUNTIME_SKIP_BINARY_PROBE === '1'
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

  // 1) node_modules（含 onnxruntime 裁剪 + win32 原生包 overlay）
  const stagedModules = path.join(targetDir, 'node_modules')
  const copied = copyDir(nodeModules, stagedModules)
  console.log(`[stage-render-runtime] node_modules 已暂存（${copied} 个文件，含 onnxruntime-node）`)

  pruneOnnxPlatforms(path.join(stagedModules, 'onnxruntime-node'))
  pruneForeignPlatformPackages(stagedModules)
  if (win32ModulesDir) {
    overlayWin32Packages(stagedModules, win32ModulesDir)
  }
  _assertWin32Packages(stagedModules)

  // 2) Chromium（整目录，坑 2）
  stageBrowser(targetDir, browserDirOrExe)

  // 3) ffmpeg + ffprobe（自包含且成对，坑 3）
  stageFfmpeg(targetDir, ffmpegPath, ffprobePath, { skipProbe })

  // 4) 记录来源与版本（便于与容器比对；计划 §0.5.2 的 MANIFEST 约定）
  const manifest = {
    stagedFrom: { sourceDir, win32ModulesDir, browserDirOrExe, ffmpegPath, ffprobePath },
    targetPlatform: TARGET_PLATFORM,
    onnxruntimePlatformsKept: TARGET_ORT_PLATFORMS,
    versions: {
      ffmpeg: _safeVersion(path.join(targetDir, _withExe('ffmpeg')), ['-hide_banner', '-version']),
      ffprobe: _safeVersion(path.join(targetDir, _withExe('ffprobe')), ['-hide_banner', '-version']),
      chromium: _safeVersion(path.join(targetDir, BROWSER_EXE), ['--version']),
    },
    note:
      '容器侧基准（llmops-render-worker）：Node v24.21.0 / Chromium 152.0.7977.82 / ' +
      'ffmpeg 5.1.9-0+deb12u1 / hyperframes 0.8.42 / onnxruntime-node 1.21.1。' +
      'Windows 侧 Chromium/ffmpeg 为独立构建，版本号可能与容器不同（详见 plan §0.5.2）。',
  }
  fs.writeFileSync(
    path.join(targetDir, 'MANIFEST.json'),
    JSON.stringify(manifest, null, 2) + '\n',
    'utf-8',
  )
  fs.writeFileSync(
    path.join(targetDir, 'SOURCE.txt'),
    `Staged from ${sourceDir}\n` +
      `hyperframes + Chromium + ffmpeg/ffprobe + onnxruntime-node\n` +
      `target platform: ${TARGET_PLATFORM} (win32 native packages overlaid)\n` +
      `onnxruntime platforms kept: ${TARGET_ORT_PLATFORMS.join(',')}\n` +
      `ffmpeg : ${manifest.versions.ffmpeg}\n` +
      `ffprobe: ${manifest.versions.ffprobe}\n` +
      `chromium: ${manifest.versions.chromium}\n`,
    'utf-8',
  )
  console.log(`[stage-render-runtime] done → ${targetDir}`)
}

if (require.main === module) {
  main()
}

module.exports = {
  main,
  checkFfmpegCapabilities,
  _isForeignPlatformDir,
  _resolveBrowserDir,
  _withExe,
}
