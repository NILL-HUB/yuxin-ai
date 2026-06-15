import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import MyAiChatView from '@/views/my-ai/MyAiChatView.vue'

const mocks = vi.hoisted(() => ({
  chatWithMyApp: vi.fn(),
  messageSuccess: vi.fn(),
  messageError: vi.fn(),
}))

vi.mock('vue-router', () => ({
  useRoute: () => ({ params: { app_id: 'app-1' } }),
}))

vi.mock('@/services/my-apps', () => ({
  chatWithMyApp: mocks.chatWithMyApp,
}))

vi.mock('@arco-design/web-vue', () => ({
  Message: {
    success: mocks.messageSuccess,
    error: mocks.messageError,
  },
}))

const inputStub = {
  props: ['modelValue', 'placeholder'],
  emits: ['update:modelValue'],
  template: '<textarea :value="modelValue" :placeholder="placeholder" @input="$emit(\'update:modelValue\', $event.target.value)" />',
}

const buttonStub = {
  props: ['loading', 'type'],
  emits: ['click'],
  template: '<button type="button" :disabled="loading" @click="$emit(\'click\')"><slot /></button>',
}

describe('MyAiChatView', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('sends message to assigned AI app', async () => {
    mocks.chatWithMyApp.mockImplementation((_appId, _req, onData) => {
      onData({ event: 'agent_message', data: { answer: '你好，我可以帮你审查合同。' } })
      return Promise.resolve()
    })
    const wrapper = mount(MyAiChatView, { global: { stubs: { 'a-textarea': inputStub, 'a-button': buttonStub } } })

    await wrapper.find('textarea[placeholder="输入你的问题"]').setValue('帮我看看合同')
    await wrapper.find('button').trigger('click')
    await flushPromises()

    expect(mocks.chatWithMyApp).toHaveBeenCalledWith('app-1', {
      query: '帮我看看合同',
      image_urls: [],
      conversation_id: '',
    }, expect.any(Function))
    expect(wrapper.text()).toContain('帮我看看合同')
    expect(wrapper.text()).toContain('你好，我可以帮你审查合同。')
  })
})
