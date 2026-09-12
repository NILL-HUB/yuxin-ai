import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'

const mocks = vi.hoisted(() => ({
  chatWithMyApp: vi.fn(),
  messageError: vi.fn(),
}))

vi.mock('@/services/my-apps', () => ({
  chatWithMyApp: mocks.chatWithMyApp,
}))

vi.mock('@arco-design/web-vue', () => ({
  Message: {
    error: mocks.messageError,
    success: vi.fn(),
  },
}))

vi.mock('@/stores/account', () => ({
  useAccountStore: () => ({ account: { id: 'acc-1', name: '小钰', email: '', avatar: '' } }),
}))

import MyAppChatPanel from '@/views/space/my-apps/components/MyAppChatPanel.vue'

const slotStub = { template: '<div><slot /></div>' }

const timelineStub = {
  props: ['messages', 'account', 'app', 'loading', 'textToSpeechEnable'],
  template: '<div data-testid="timeline">{{ messages.length }}</div>',
}

const composerStub = {
  props: ['modelValue', 'placeholder', 'submitLoading'],
  emits: ['update:modelValue', 'submit', 'clear', 'keydown', 'input'],
  template:
    '<div data-testid="composer"><textarea :value="modelValue" @input="$emit(\'update:modelValue\', $event.target.value)" /><button data-testid="send" @click="$emit(\'submit\')">send</button></div>',
}

const globalStubs = {
  'chat-message-timeline': timelineStub,
  'chat-composer': composerStub,
  'a-avatar': slotStub,
  ToolConfirmationCard: slotStub,
}

const mountPanel = async () => {
  const wrapper = mount(MyAppChatPanel, {
    props: { app: { id: 'app-1', name: '智能写作助手', icon: '' }, sourceLabel: '管理员分配' },
    global: { stubs: globalStubs },
  })
  await flushPromises()
  return wrapper
}

describe('MyAppChatPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('shows the empty state before any message', async () => {
    const wrapper = await mountPanel()
    expect(wrapper.text()).toContain('发送一条消息开始对话')
    expect(wrapper.text()).toContain('智能写作助手')
  })

  it('sends through the my-app chat API and renders the streamed answer', async () => {
    mocks.chatWithMyApp.mockImplementation(
      async (_appId: string, _req: unknown, onData: (e: unknown) => void) => {
        onData({ event: 'agent_message', data: { id: 'm1', answer: '你好呀', conversation_id: 'c1' } })
        onData({ event: 'agent_end', data: { id: 'm1', task_id: 't1' } })
      },
    )

    const wrapper = await mountPanel()
    await wrapper.find('textarea').setValue('帮我写一段文案')
    await wrapper.find('[data-testid="send"]').trigger('click')
    await flushPromises()

    expect(mocks.chatWithMyApp).toHaveBeenCalledWith(
      'app-1',
      expect.objectContaining({ query: '帮我写一段文案' }),
      expect.any(Function),
    )
  })
})
