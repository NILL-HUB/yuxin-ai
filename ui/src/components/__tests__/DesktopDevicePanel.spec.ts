import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, shallowMount } from '@vue/test-utils'

import DesktopDevicePanel from '@/components/DesktopDevicePanel.vue'

let updateStatusHandler: ((payload: Record<string, unknown>) => void) | null = null
const updateStatusDispose = vi.fn()

const api = {
  workersStatus: vi.fn().mockResolvedValue({
    os: { running: true, pid: 1 },
    computer: { running: true, pid: 2 },
  }),
  getWorkerVersions: vi.fn().mockResolvedValue({
    os: { running: true, pid: 1, version: '0.1.0' },
    computer: { running: true, pid: 2, version: '0.1.0' },
  }),
  getLaunchAtLogin: vi.fn().mockResolvedValue(false),
  setLaunchAtLogin: vi.fn().mockResolvedValue(true),
  checkForUpdates: vi.fn().mockResolvedValue({ ok: true }),
  recycleList: vi.fn().mockResolvedValue({
    entries: [{ entry_id: 'e1', original_path: 'C:/tmp/old.txt' }],
  }),
  recycleRestore: vi.fn().mockResolvedValue({ ok: true }),
  wakeStatus: vi.fn().mockResolvedValue({ running: false }),
  wakeEnable: vi.fn().mockResolvedValue(true),
  wakeDisable: vi.fn().mockResolvedValue(true),
  onUpdateStatus: vi.fn((callback: (payload: Record<string, unknown>) => void) => {
    updateStatusHandler = callback
    return updateStatusDispose
  }),
}

const ButtonStub = {
  name: 'AButton',
  props: ['loading', 'type', 'size'],
  template: '<button><slot /></button>',
}

const SwitchStub = {
  name: 'ASwitch',
  props: ['modelValue', 'size'],
  emits: ['change'],
  template: '<input type="checkbox" :checked="modelValue" @change="$emit(\'change\', !modelValue)" />',
}

describe('DesktopDevicePanel', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    updateStatusHandler = null
    Object.defineProperty(window, 'yujianwoDesktop', { value: api, configurable: true })
  })

  it('renders workers, recycle items and wake toggle', async () => {
    const wrapper = shallowMount(DesktopDevicePanel, {
      global: { stubs: { 'a-button': ButtonStub, 'a-switch': SwitchStub } },
    })
    await flushPromises()

    expect(wrapper.text()).toContain('os')
    expect(wrapper.text()).toContain('computer')
    expect(wrapper.text()).toContain('C:/tmp/old.txt')
    expect(api.workersStatus).toHaveBeenCalled()
    expect(api.getWorkerVersions).toHaveBeenCalled()
    expect(api.getLaunchAtLogin).toHaveBeenCalled()
    expect(api.recycleList).toHaveBeenCalled()
  })

  it('shows worker version and autostart switch when launched from desktop', async () => {
    const wrapper = shallowMount(DesktopDevicePanel, {
      global: { stubs: { 'a-button': ButtonStub, 'a-switch': SwitchStub } },
    })
    await flushPromises()

    expect(wrapper.text()).toContain('0.1.0')
    expect(api.setLaunchAtLogin).not.toHaveBeenCalled()

    await wrapper.find('input[type="checkbox"]').setValue(true)

    expect(api.setLaunchAtLogin).toHaveBeenCalledWith(true)
  })

  it('toggles launch at login off when switch is flipped off', async () => {
    api.getLaunchAtLogin.mockResolvedValueOnce(true)
    const wrapper = shallowMount(DesktopDevicePanel, {
      global: { stubs: { 'a-button': ButtonStub, 'a-switch': SwitchStub } },
    })
    await flushPromises()

    await wrapper.find('input[type="checkbox"]').setValue(false)

    expect(api.setLaunchAtLogin).toHaveBeenCalledWith(false)
  })

  it('shows updater disabled note when checkForUpdates returns ok:false', async () => {
    api.checkForUpdates.mockResolvedValueOnce({ ok: false, reason: 'updater_disabled' })
    const wrapper = shallowMount(DesktopDevicePanel, {
      global: { stubs: { 'a-button': ButtonStub, 'a-switch': SwitchStub } },
    })
    await flushPromises()

    await wrapper.findAll('button')[1].trigger('click')
    await flushPromises()

    expect(api.checkForUpdates).toHaveBeenCalled()
  })

  it('restores an entry from recycle bin', async () => {
    const wrapper = shallowMount(DesktopDevicePanel, {
      global: { stubs: { 'a-button': ButtonStub, 'a-switch': SwitchStub } },
    })
    await flushPromises()

    await wrapper.findAll('button')[2].trigger('click')

    expect(api.recycleRestore).toHaveBeenCalledWith({ entry_id: 'e1' })
  })

  it('shows the update result pushed by the main process', async () => {
    const wrapper = shallowMount(DesktopDevicePanel, {
      global: { stubs: { 'a-button': ButtonStub, 'a-switch': SwitchStub } },
    })
    await flushPromises()

    expect(api.onUpdateStatus).toHaveBeenCalled()

    updateStatusHandler?.({ status: 'available', version: '0.1.1', manual: true })
    await flushPromises()
    expect(wrapper.text()).toContain('发现新版本 0.1.1')

    updateStatusHandler?.({ status: 'not-available', manual: true })
    await flushPromises()
    expect(wrapper.text()).toContain('已是最新版本')

    updateStatusHandler?.({ status: 'error', manual: true })
    await flushPromises()
    expect(wrapper.text()).toContain('检查更新失败')
  })

  it('stays quiet on automatic not-available checks', async () => {
    const wrapper = shallowMount(DesktopDevicePanel, {
      global: { stubs: { 'a-button': ButtonStub, 'a-switch': SwitchStub } },
    })
    await flushPromises()

    updateStatusHandler?.({ status: 'not-available', manual: false })
    await flushPromises()

    expect(wrapper.text()).not.toContain('已是最新版本')
  })

  it('disposes the update status subscription on unmount', async () => {
    const wrapper = shallowMount(DesktopDevicePanel, {
      global: { stubs: { 'a-button': ButtonStub, 'a-switch': SwitchStub } },
    })
    await flushPromises()

    wrapper.unmount()

    expect(updateStatusDispose).toHaveBeenCalled()
  })

  it('hides itself when desktop api is missing', async () => {
    Object.defineProperty(window, 'yujianwoDesktop', { value: undefined, configurable: true })
    const wrapper = shallowMount(DesktopDevicePanel)
    await flushPromises()

    expect(wrapper.find('.border.rounded-lg').exists()).toBe(false)
  })
})
