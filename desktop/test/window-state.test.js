const { test } = require('node:test')
const assert = require('node:assert')
const path = require('node:path')
const os = require('node:os')
const fs = require('node:fs')
const { computeWindowOptions, loadState, saveState } = require('../window-state')

const displays = [{ workArea: { x: 0, y: 0, width: 1920, height: 1080 } }]

test('computeWindowOptions falls back to defaults without state', () => {
  const opts = computeWindowOptions(null, displays)
  assert.equal(opts.width, 1280)
  assert.equal(opts.height, 860)
  assert.equal(opts.x, undefined)
})

test('computeWindowOptions restores saved bounds when on screen', () => {
  const opts = computeWindowOptions(
    { width: 1000, height: 700, x: 100, y: 100, isMaximized: false },
    displays,
  )
  assert.equal(opts.width, 1000)
  assert.equal(opts.height, 700)
  assert.equal(opts.x, 100)
  assert.equal(opts.y, 100)
})

test('computeWindowOptions drops off-screen position', () => {
  const opts = computeWindowOptions(
    { width: 1000, height: 700, x: 99999, y: 99999, isMaximized: false },
    displays,
  )
  assert.equal(opts.x, undefined)
  assert.equal(opts.y, undefined)
})

test('computeWindowOptions clamps to minimums', () => {
  const opts = computeWindowOptions({ width: 100, height: 100 }, displays)
  assert.equal(opts.width, 940)
  assert.equal(opts.height, 620)
})

test('saveState then loadState round-trips bounds and maximized flag', () => {
  const filePath = path.join(fs.mkdtempSync(path.join(os.tmpdir(), 'wstate-')), 'window-state.json')
  const fakeWin = {
    isDestroyed: () => false,
    isMaximized: () => true,
    getNormalBounds: () => ({ x: 50, y: 60, width: 1100, height: 720 }),
  }
  saveState(filePath, fakeWin)
  const state = loadState(filePath)
  assert.equal(state.width, 1100)
  assert.equal(state.height, 720)
  assert.equal(state.x, 50)
  assert.equal(state.y, 60)
  assert.equal(state.isMaximized, true)
})

test('loadState returns null for missing or corrupt file', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'wstate2-'))
  assert.equal(loadState(path.join(dir, 'nope.json')), null)
  const bad = path.join(dir, 'bad.json')
  fs.writeFileSync(bad, '{ not json', 'utf-8')
  assert.equal(loadState(bad), null)
})
