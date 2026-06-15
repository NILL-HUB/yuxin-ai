import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import MyAiView from '@/views/my-ai/MyAiView.vue'

const push = vi.fn()
const mocks = vi.hoisted(() => ({
  listMyApps: vi.fn(),
  messageError: vi.fn(),
}))

vi.mock('vue-router', () => ({
  useRouter: () => ({ push }),
}))

vi.mock('@/services/my-apps', () => ({
  listMyApps: mocks.listMyApps,
}))

vi.mock('@arco-design/web-vue', () => ({
  Message: { error: mocks.messageError },
}))

const buttonStub = {
  props: ['loading', 'type'],
  emits: ['click'],
  template: '<button type="button" :disabled="loading" @click="$emit(\'click\')"><slot /></button>',
}

describe('MyAiView', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    push.mockClear()
  })

  it('loads and renders assigned AI apps', async () => {
    mocks.listMyApps.mockResolvedValue({ list: [{ id: 'app-1', assignment_id: 'assignment-1', name: '合同审查助手', icon: '🤖', description: '审查合同风险', assigned_at: 1893456000 }] })

    const wrapper = mount(MyAiView, { global: { stubs: { 'a-button': buttonStub } } })
    await flushPromises()

    expect(mocks.listMyApps).toHaveBeenCalled()
    expect(wrapper.text()).toContain('我的 AI 功能')
    expect(wrapper.text()).toContain('合同审查助手')
    expect(wrapper.text()).toContain('审查合同风险')
  })

  it('opens assigned AI app chat page', async () => {
    mocks.listMyApps.mockResolvedValue({ list: [{ id: 'app-1', assignment_id: 'assignment-1', name: '合同审查助手', icon: '🤖', description: '审查合同风险', assigned_at: 1893456000 }] })

    const wrapper = mount(MyAiView, { global: { stubs: { 'a-button': buttonStub } } })
    await flushPromises()
    await wrapper.find('button').trigger('click')

    expect(push).toHaveBeenCalledWith('/my-ai/app-1')
  })
})
