const { test } = require('node:test')
const assert = require('node:assert')
const path = require('node:path')
const os = require('node:os')
const fs = require('node:fs')
const { createCredentialStore } = require('../credential-store')

const fakeSafeStorage = {
  isEncryptionAvailable: () => true,
  encryptString: (s) => Buffer.from(`enc:${s}`, 'utf-8'),
  decryptString: (b) => String(b).replace(/^enc:/, ''),
}

test('save then load returns token', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'cred-'))
  const store = createCredentialStore({
    filePath: path.join(dir, 'cred.bin'),
    safeStorage: fakeSafeStorage,
  })
  store.save('token-abc')
  assert.equal(store.load(), 'token-abc')
})

test('load with no file returns null', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'cred2-'))
  const store = createCredentialStore({
    filePath: path.join(dir, 'nope.bin'),
    safeStorage: fakeSafeStorage,
  })
  assert.equal(store.load(), null)
})

test('clear removes file', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'cred3-'))
  const store = createCredentialStore({
    filePath: path.join(dir, 'c.bin'),
    safeStorage: fakeSafeStorage,
  })
  store.save('x')
  store.clear()
  assert.equal(store.load(), null)
})
