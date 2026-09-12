import { afterEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import DesktopTitleBar from '@/components/DesktopTitleBar.vue'
import zhCN from '@/i18n/messages/zh-CN'
import enUS from '@/i18n/messages/en-US'

const makeI18n = () =>
  createI18n({
    legacy: false,
    locale: 'zh-CN',
    fallbackLocale: 'en-US',
    messages: { 'zh-CN': zhCN, 'en-US': enUS },
  })

const bridge = {
  minimize: vi.fn(),
  toggleMaximize: vi.fn(),
  close: vi.fn(),
  isMaximized: vi.fn().mockResolvedValue(false),
  getOverlayState: vi.fn().mockResolvedValue({ overlay: true }),
  onMaximizedChanged: vi.fn().mockReturnValue(() => {}),
}

describe('DesktopTitleBar', () => {
  afterEach(() => {
    Object.defineProperty(window, 'windowControls', { value: undefined, configurable: true })
    vi.clearAllMocks()
  })

  it('does not render in web runtime without windowControls bridge', () => {
    const wrapper = mount(DesktopTitleBar, { global: { plugins: [makeI18n()] } })
    expect(wrapper.find('[data-desktop-titlebar]').exists()).toBe(false)
  })

  it('renders when windowControls bridge is present', async () => {
    Object.defineProperty(window, 'windowControls', { value: bridge, configurable: true })
    const wrapper = mount(DesktopTitleBar, { global: { plugins: [makeI18n()] } })
    await wrapper.vm.$nextTick()
    expect(wrapper.find('[data-desktop-titlebar]').exists()).toBe(true)
    expect(wrapper.text()).toContain('钰见我')
  })

  it('minimize/close call bridge methods', async () => {
    Object.defineProperty(window, 'windowControls', { value: bridge, configurable: true })
    const wrapper = mount(DesktopTitleBar, { global: { plugins: [makeI18n()] } })
    await wrapper.vm.$nextTick()
    // overlay placeholder 路径下无自绘按钮；切换为 overlay=false 验证按钮
    bridge.getOverlayState.mockResolvedValueOnce({ overlay: false })
    const nav = navigator as Navigator & {
      windowControlsOverlay?: { visible: boolean; getTitlebarAreaRect: () => DOMRect }
    }
    Object.defineProperty(nav, 'windowControlsOverlay', {
      value: { visible: false, getTitlebarAreaRect: () => ({ width: 0 }) as DOMRect },
      configurable: true,
    })
    wrapper.vm.$forceUpdate()
    await wrapper.vm.$nextTick()
    await wrapper.vm.$nextTick()

    const buttons = wrapper.findAll('button')
    expect(buttons.length).toBeGreaterThanOrEqual(3)
    await buttons[0].trigger('click')
    expect(bridge.minimize).toHaveBeenCalled()
    await buttons[2].trigger('click')
    expect(bridge.close).toHaveBeenCalled()
  })
})
