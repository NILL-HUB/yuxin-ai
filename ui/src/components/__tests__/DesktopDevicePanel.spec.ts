import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, shallowMount } from '@vue/test-utils'

import DesktopDevicePanel from '@/components/DesktopDevicePanel.vue'

const api = {
  workersStatus: vi.fn().mockResolvedValue({
    os: { running: true, pid: 1 },
    computer: { running: true, pid: 2 },
  }),
  recycleList: vi.fn().mockResolvedValue({
    entries: [{ entry_id: 'e1', original_path: 'C:/tmp/old.txt' }],
  }),
  recycleRestore: vi.fn().mockResolvedValue({ ok: true }),
  wakeStatus: vi.fn().mockResolvedValue({ running: false }),
  wakeEnable: vi.fn().mockResolvedValue(true),
  wakeDisable: vi.fn().mockResolvedValue(true),
}

const ButtonStub = {
  name: 'AButton',
  props: ['loading', 'type', 'size'],
  template: '<button><slot /></button>',
}

describe('DesktopDevicePanel', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    Object.defineProperty(window, 'yuxinDesktop', { value: api, configurable: true })
  })

  it('renders workers, recycle items and wake toggle', async () => {
    const wrapper = shallowMount(DesktopDevicePanel, {
      global: { stubs: { 'a-button': ButtonStub } },
    })
    await flushPromises()

    expect(wrapper.text()).toContain('os')
    expect(wrapper.text()).toContain('computer')
    expect(wrapper.text()).toContain('C:/tmp/old.txt')
    expect(api.workersStatus).toHaveBeenCalled()
    expect(api.recycleList).toHaveBeenCalled()
  })

  it('restores an entry from recycle bin', async () => {
    const wrapper = shallowMount(DesktopDevicePanel, {
      global: { stubs: { 'a-button': ButtonStub } },
    })
    await flushPromises()

    await wrapper.findAll('button')[1].trigger('click')

    expect(api.recycleRestore).toHaveBeenCalledWith({ entry_id: 'e1' })
  })

  it('hides itself when desktop api is missing', async () => {
    Object.defineProperty(window, 'yuxinDesktop', { value: undefined, configurable: true })
    const wrapper = shallowMount(DesktopDevicePanel)
    await flushPromises()

    expect(wrapper.find('.border.rounded-lg').exists()).toBe(false)
  })
})
