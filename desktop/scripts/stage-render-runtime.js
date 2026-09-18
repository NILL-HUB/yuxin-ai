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
// 体积参考：node_modules 约 198MB（含裁剪后的 onnxruntime），Chromium 约 338MB。
// 安装包增量约 175–215MB。
//
// 源缺失时打印提示并跳过（不阻断打包），与 stage-cua-driver.js 行为一致。

const fs = require('node:fs')
const path = require('node:path')

// onnxruntime-node 跨平台裁剪：仅保留目标平台（默认 win32）
const TARGET_ORT_PLATFORMS = (process.env.ORT_PLATFORMS || 'win32')
  .split(',')
  .map((s) => s.trim())
  .filter(Boolean)

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

function main() {
  const sourceDir = process.env.RENDER_RUNTIME_SOURCE_DIR || ''
  const targetDir =
    process.env.STAGE_TARGET_DIR || path.join(__dirname, '..', 'vendor', 'render-runtime')

  // 目录必须始终存在，否则 electron-builder 的 extraResources 会因源缺失而失败
  fs.mkdirSync(targetDir, { recursive: true })

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

  const copied = copyDir(nodeModules, path.join(targetDir, 'node_modules'))
  console.log(`[stage-render-runtime] node_modules 已暂存（${copied} 个文件，含 onnxruntime-node）`)

  // 裁剪 onnxruntime 的非目标平台目录（536MB → 68MB）
  pruneOnnxPlatforms(path.join(targetDir, 'node_modules', 'onnxruntime-node'))

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
      `onnxruntime platforms kept: ${TARGET_ORT_PLATFORMS.join(',')}\n`,
    'utf-8',
  )
  console.log(`[stage-render-runtime] done → ${targetDir}`)
}

main()
