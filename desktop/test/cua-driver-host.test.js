const { test } = require('node:test')
const assert = require('node:assert')
const path = require('node:path')
const os = require('node:os')
const fs = require('node:fs')

const {
  resolveCuaDriverExe,
  cuaDriverStatus,
  stopCuaDriver,
} = require('../cua-driver-host')

test('resolveCuaDriverExe returns explicit path when it exists', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'cua-exe-'))
  const exe = path.join(dir, 'cua-driver.exe')
  fs.writeFileSync(exe, 'stub')

  const prev = process.env.CUA_DRIVER_EXE
  process.env.CUA_DRIVER_EXE = exe
  try {
    assert.equal(resolveCuaDriverExe(), exe)
  } finally {
    if (prev === undefined) delete process.env.CUA_DRIVER_EXE
    else process.env.CUA_DRIVER_EXE = prev
  }
})

test('resolveCuaDriverExe ignores explicit path that does not exist', () => {
  const prev = process.env.CUA_DRIVER_EXE
  process.env.CUA_DRIVER_EXE = path.join(os.tmpdir(), 'definitely-missing-cua-driver.exe')
  try {
    const resolved = resolveCuaDriverExe({ resourcesDir: path.join(os.tmpdir(), 'no-res') })
    assert.notEqual(resolved, process.env.CUA_DRIVER_EXE)
  } finally {
    if (prev === undefined) delete process.env.CUA_DRIVER_EXE
    else process.env.CUA_DRIVER_EXE = prev
  }
})

test('resolveCuaDriverExe finds binary under resourcesDir/cua-driver', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'cua-res-'))
  const sub = path.join(dir, 'cua-driver')
  fs.mkdirSync(sub, { recursive: true })
  const exe = path.join(sub, 'cua-driver.exe')
  fs.writeFileSync(exe, 'stub')

  const prev = process.env.CUA_DRIVER_EXE
  delete process.env.CUA_DRIVER_EXE
  try {
    assert.equal(resolveCuaDriverExe({ resourcesDir: dir }), exe)
  } finally {
    if (prev !== undefined) process.env.CUA_DRIVER_EXE = prev
  }
})

test('resolveCuaDriverExe returns empty string when nothing found', () => {
  const prev = process.env.CUA_DRIVER_EXE
  delete process.env.CUA_DRIVER_EXE
  try {
    const resolved = resolveCuaDriverExe({ resourcesDir: path.join(os.tmpdir(), 'empty-res-dir') })
    assert.equal(typeof resolved, 'string')
  } finally {
    if (prev !== undefined) process.env.CUA_DRIVER_EXE = prev
  }
})

test('cuaDriverStatus reports available/running/exePath shape', () => {
  const status = cuaDriverStatus()
  assert.equal(typeof status.available, 'boolean')
  assert.equal(typeof status.running, 'boolean')
  assert.equal(typeof status.exePath, 'string')
})

test('stopCuaDriver is safe to call when no daemon started', () => {
  assert.doesNotThrow(() => stopCuaDriver())
})
