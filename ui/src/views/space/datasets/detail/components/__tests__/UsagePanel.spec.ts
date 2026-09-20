import { describe, expect, it, vi, beforeEach } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'

const mocks = vi.hoisted(() => ({ getStorageUsage: vi.fn(), resolveUpgradeUrl: vi.fn() }))
vi.mock('@/services/storage-usage', () => ({
  getStorageUsage: mocks.getStorageUsage,
  resolveUpgradeUrl: mocks.resolveUpgradeUrl,
}))
vi.mock('@arco-design/web-vue', () => ({
  Message: { error: vi.fn() },
  Progress: { template: '<div />' },
}))

const messages = {
  'zh-CN': {
    space: {
      datasets: {
        detail: {
          usage: {
            title: '存储用量',
            refresh: '刷新',
            loadFailed: '用量加载失败，请稍后重试',
            upgrade: '扩容',
          },
        },
      },
    },
  },
  'en-US': {
    space: {
      datasets: {
        detail: {
          usage: {
            title: 'Storage Usage',
            refresh: 'Refresh',
            loadFailed: 'Failed to load usage',
            upgrade: 'Upgrade',
          },
        },
      },
    },
  },
}
const i18n = createI18n({ legacy: false, locale: 'zh-CN', fallbackLocale: 'en-US', messages })

const stubs = {
  'a-progress': { template: '<div />' },
  'a-button': { template: '<button type="button"><slot /></button>' },
  'a-skeleton-line': { template: '<div />' },
}

import UsagePanel from '@/views/space/datasets/detail/components/UsagePanel.vue'

describe('UsagePanel', () => {
  beforeEach(() => {
    mocks.getStorageUsage.mockReset()
    mocks.resolveUpgradeUrl.mockReturnValue('/membership')
  })

  it('挂载后拉取用量并渲染百分比', async () => {
    mocks.getStorageUsage.mockResolvedValue({
      data: { total_bytes: 100, used_bytes: 30, remaining_bytes: 70, usage_percent: 30.0 },
    })
    const wrapper = mount(UsagePanel, {
      global: { plugins: [i18n], stubs },
    })
    await flushPromises()
    expect(mocks.getStorageUsage).toHaveBeenCalled()
    expect(wrapper.text()).toContain('30.0')
    expect(wrapper.text()).toContain('100.0')
  })

  it('拉取失败渲染错误文案且不崩溃', async () => {
    mocks.getStorageUsage.mockRejectedValue(new Error('boom'))
    const wrapper = mount(UsagePanel, {
      global: { plugins: [i18n], stubs },
    })
    await flushPromises()
    expect(wrapper.text()).toContain('用量加载失败，请稍后重试')
  })
})