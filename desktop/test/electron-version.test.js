const { test } = require('node:test')
const assert = require('node:assert')
const { execFileSync } = require('node:child_process')
const path = require('node:path')
const fs = require('node:fs')

// 容器侧基准（api/Dockerfile.render 的 ARG NODE_IMAGE=node:24-bookworm-slim，实测 24.21.0）
const REQUIRED_NODE_MAJOR = 24

function electronBinary() {
  const base = path.join(__dirname, '..', 'node_modules', 'electron', 'dist')
  if (process.platform === 'win32') return path.join(base, 'electron.exe')
  if (process.platform === 'darwin') return path.join(base, 'Electron.app', 'Contents', 'MacOS', 'Electron')
  return path.join(base, 'electron')
}

test('desktop electron bundles Node 24 to match the render container', () => {
  const bin = electronBinary()
  assert.ok(fs.existsSync(bin), 'electron 二进制不存在，请先 npm install')
  const out = execFileSync(bin, ['-e', 'console.log(process.versions.node)'], {
    env: { ...process.env, ELECTRON_RUN_AS_NODE: '1' },
    encoding: 'utf-8',
  }).trim()
  const major = Number.parseInt(out.split('.')[0], 10)
  assert.equal(
    major,
    REQUIRED_NODE_MAJOR,
    `Electron 内置 Node 为 ${out}，要求 major=${REQUIRED_NODE_MAJOR}（与容器 node:24 对齐）`,
  )
})

test('electron binary can run as node with ESM support', () => {
  const bin = electronBinary()
  const out = execFileSync(
    bin,
    ['-e', "import('node:module').then(() => console.log('esm-ok'))"],
    {
      env: { ...process.env, ELECTRON_RUN_AS_NODE: '1' },
      encoding: 'utf-8',
    },
  ).trim()
  assert.match(out, /esm-ok/)
})
