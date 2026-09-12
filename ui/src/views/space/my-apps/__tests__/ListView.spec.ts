import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'

const mocks = vi.hoisted(() => ({
  listMyApps: vi.fn(),
  chatWithMyApp: vi.fn(),
  messageError: vi.fn(),
}))

vi.mock('@/services/my-apps', () => ({
  listMyApps: mocks.listMyApps,
  chatWithMyApp: mocks.chatWithMyApp,
}))

vi.mock('@arco-design/web-vue', () => ({
  Message: {
    error: mocks.messageError,
    success: vi.fn(),
  },
}))

import ListView from '@/views/space/my-apps/ListView.vue'

const slotStub = { template: '<div><slot /></div>' }

const globalStubs = {
  'icon-search': slotStub,
  'icon-apps': slotStub,
  'icon-branch': slotStub,
  'icon-user': slotStub,
  'icon-right': slotStub,
  'icon-left': slotStub,
  'icon-message': slotStub,
  'icon-send': slotStub,
  'a-textarea': slotStub,
  MyAppChatPanel: {
    props: ['app', 'sourceLabel'],
    template: '<div data-testid="my-app-chat-panel">{{ app.name }}</div>',
  },
}

const mountView = async () => {
  const wrapper = mount(ListView, { global: { stubs: globalStubs } })
  await flushPromises()
  return wrapper
}

describe('my-apps ListView', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders apps returned by the real API', async () => {
    mocks.listMyApps.mockResolvedValue({
      code: 'success',
      message: '',
      data: {
        list: [
          {
            id: 'app-1',
            assignment_id: 'asg-1',
            name: '智能写作助手',
            icon: '',
            description: '帮你写各种文案',
            assigned_at: 1893456000,
            source: 'assigned',
            status: 'published',
            can_edit: false,
          },
        ],
      },
    })

    const wrapper = await mountView()

    expect(mocks.listMyApps).toHaveBeenCalledTimes(1)
    expect(wrapper.text()).toContain('智能写作助手')
    expect(wrapper.text()).toContain('帮你写各种文案')
    expect(wrapper.text()).not.toContain('暂无应用')
  })

  it('shows empty state when API returns no apps', async () => {
    mocks.listMyApps.mockResolvedValue({ code: 'success', message: '', data: { list: [] } })

    const wrapper = await mountView()

    expect(wrapper.text()).toContain('暂无应用')
    expect(wrapper.findAll('article')).toHaveLength(0)
  })

  it('enters the reused agent chat panel when a card is opened', async () => {
    mocks.listMyApps.mockResolvedValue({
      code: 'success',
      message: '',
      data: {
        list: [
          {
            id: 'app-1',
            assignment_id: 'asg-1',
            name: '智能写作助手',
            icon: '',
            description: '帮你写各种文案',
            assigned_at: 1893456000,
            source: 'assigned',
            status: 'published',
            can_edit: false,
          },
        ],
      },
    })

    const wrapper = await mountView()
    expect(wrapper.find('[data-testid="my-app-chat-panel"]').exists()).toBe(false)

    await wrapper.find('article').trigger('click')

    const panel = wrapper.find('[data-testid="my-app-chat-panel"]')
    expect(panel.exists()).toBe(true)
    expect(panel.text()).toContain('智能写作助手')
  })
})
