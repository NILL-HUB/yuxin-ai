'use strict'

const fs = require('node:fs')
const path = require('node:path')

// HyperFrames CLI 需要「node + cli.js」两段式调用，而服务端 HYPERFRAMES_CLI_BIN
// 只接受单个可执行文件路径，故必须生成 shim 把 Electron 的 Node 包在中间。
// 运行时二进制随安装包分发（见 §0.5.2），路径位于 resources/render-runtime/。
// 详见 docs/superpowers/plans/2026-09-18-local-first-render-offload.md §0.5.1。

function _shimFileName() {
  return process.platform === 'win32' ? 'hyperframes.cmd' : 'hyperframes'
}

function resolveRuntimePaths({ env, resourcesDir }) {
  const pick = (key) => String((env && env[key]) || '').trim()
  // 随包分发：运行时固定在 resources/render-runtime/（见 §0.5.2）
  const runtimeDir = path.join(resourcesDir, 'render-runtime')
  const withExe = (name) =>
    process.platform === 'win32' ? `${name}.exe` : name
  return {
    runtimeDir,
    cliJsPath: path.join(runtimeDir, 'node_modules', 'hyperframes', 'dist', 'cli.js'),
    browserPath: pick('HYPERFRAMES_BROWSER_PATH') ||
      path.join(runtimeDir, withExe('chrome-headless-shell')),
    ffmpegPath: pick('HYPERFRAMES_FFMPEG_PATH') ||
      path.join(runtimeDir, withExe('ffmpeg')),
    ffprobePath: pick('HYPERFRAMES_FFPROBE_PATH') ||
      path.join(runtimeDir, withExe('ffprobe')),
  }
}

function ensureCliShim({ electronPath, cliJsPath, targetDir }) {
  fs.mkdirSync(targetDir, { recursive: true })
  const shimPath = path.join(targetDir, _shimFileName())
  if (process.platform === 'win32') {
    const content = [
      '@echo off',
      'set ELECTRON_RUN_AS_NODE=1',
      `"${electronPath}" "${cliJsPath}" %*`,
      '',
    ].join('\r\n')
    fs.writeFileSync(shimPath, content, 'utf-8')
  } else {
    const content = [
      '#!/bin/sh',
      'export ELECTRON_RUN_AS_NODE=1',
      `exec "${electronPath}" "${cliJsPath}" "$@"`,
      '',
    ].join('\n')
    fs.writeFileSync(shimPath, content, 'utf-8')
    fs.chmodSync(shimPath, 0o755)
  }
  return shimPath
}

module.exports = { resolveRuntimePaths, ensureCliShim, _shimFileName }
