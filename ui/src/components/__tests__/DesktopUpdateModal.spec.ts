import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, shallowMount } from '@vue/test-utils'

import DesktopUpdateModal from '@/components/DesktopUpdateModal.vue'

type UpdatePayload = {
  status: string
  version?: string | null
  releaseNotes?: string
  manual?: boolean
}

let emitStatus: ((payload: UpdatePayload) => void) | null = null
let disposeStatus: ReturnType<typeof vi.fn>

const api = {
  quitAndInstall: vi.fn().mockResolvedValue({ ok: true }),
  onUpdateStatus: vi.fn((callback: (payload: UpdatePayload) => void) => {
    emitStatus = callback
    return disposeStatus
  }),
}

const ModalStub = {
  name: 'AModal',
  props: ['visible', 'width', 'maskClosable'],
  template:
    '<div v-if="visible" class="update-modal"><slot name="title" /><slot /><slot name="footer" /></div>',
}

const ButtonStub = {
  name: 'AButton',
  props: ['loading', 'type'],
  emits: ['click'],
  template: '<button @click="$emit(\'click\')"><slot /></button>',
}

const mountModal = () =>
  shallowMount(DesktopUpdateModal, {
    global: { stubs: { 'a-modal': ModalStub, 'a-button': ButtonStub } },
  })

describe('DesktopUpdateModal', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    emitStatus = null
    disposeStatus = vi.fn()
    Object.defineProperty(window, 'yujianwoDesktop', { value: api, configurable: true })
  })

  it('opens with version and release notes when an update is available', async () => {
    const wrapper = mountModal()
    await flushPromises()

    expect(wrapper.find('.update-modal').exists()).toBe(false)

    emitStatus?.({ status: 'available', version: '0.1.1', releaseNotes: '新增更新弹窗\n修复设备在线状态' })
    await flushPromises()

    const modal = wrapper.find('.update-modal')
    expect(modal.exists()).toBe(true)
    expect(modal.text()).toContain('0.1.1')
    expect(modal.text()).toContain('新增更新弹窗')
    expect(modal.text()).toContain('修复设备在线状态')
    expect(modal.text()).toContain('发现新版本')
  })

  it('shows the empty notes hint when release notes are missing', async () => {
    const wrapper = mountModal()
    await flushPromises()

    emitStatus?.({ status: 'available', version: '0.1.1', releaseNotes: '' })
    await flushPromises()

    expect(wrapper.find('.update-modal').text()).toContain('本次更新暂无说明')
  })

  it('does not open the modal for non-available statuses', async () => {
    const wrapper = mountModal()
    await flushPromises()

    emitStatus?.({ status: 'not-available', manual: true })
    emitStatus?.({ status: 'checking' })
    await flushPromises()

    expect(wrapper.find('.update-modal').exists()).toBe(false)
  })

  it('offers restart-and-install once the package is downloaded', async () => {
    const wrapper = mountModal()
    await flushPromises()

    emitStatus?.({ status: 'available', version: '0.1.1', releaseNotes: '甲' })
    await flushPromises()

    emitStatus?.({ status: 'downloaded', version: '0.1.1', releaseNotes: '甲' })
    await flushPromises()

    const modal = wrapper.find('.update-modal')
    expect(modal.text()).toContain('更新已就绪')

    const restartButton = wrapper
      .findAll('button')
      .find((button) => button.text().includes('立即重启并安装'))
    expect(restartButton).toBeTruthy()

    await restartButton!.trigger('click')
    await flushPromises()

    expect(api.quitAndInstall).toHaveBeenCalledTimes(1)
  })

  it('disposes the update-status subscription on unmount', async () => {
    const wrapper = mountModal()
    await flushPromises()

    wrapper.unmount()

    expect(api.onUpdateStatus).toHaveBeenCalledTimes(1)
    expect(disposeStatus).toHaveBeenCalledTimes(1)
  })

  it('renders nothing when the desktop bridge is absent', async () => {
    Object.defineProperty(window, 'yujianwoDesktop', { value: undefined, configurable: true })
    const wrapper = mountModal()
    await flushPromises()

    expect(wrapper.find('.update-modal').exists()).toBe(false)
    expect(api.onUpdateStatus).not.toHaveBeenCalled()
  })
})