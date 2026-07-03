import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { useAdminStore } from '@/stores/admin'
import AdminWorkflowsView from '@/views/admin/AdminWorkflowsView.vue'

const mocks = vi.hoisted(() => ({
  listAdminWorkflows: vi.fn(),
  routerPush: vi.fn(),
  messageSuccess: vi.fn(),
  messageError: vi.fn(),
}))

vi.mock('@/services/admin-workflows', () => ({
  listAdminWorkflows: mocks.listAdminWorkflows,
}))

vi.mock('vue-router', async () => {
  const actual = await vi.importActual<typeof import('vue-router')>('vue-router')
  return {
    ...actual,
    useRouter: () => ({
      push: mocks.routerPush,
    }),
  }
})

vi.mock('@arco-design/web-vue', async () => {
  const actual = await vi.importActual<typeof import('@arco-design/web-vue')>('@arco-design/web-vue')
  return {
    ...actual,
    Message: {
      success: mocks.messageSuccess,
      error: mocks.messageError,
    },
  }
})

const inputStub = {
  props: ['modelValue', 'placeholder'],
  emits: ['update:modelValue'],
  template:
    '<input :value="modelValue" :placeholder="placeholder" @input="$emit(\'update:modelValue\', $event.target.value)" />',
}

const selectStub = {
  props: ['modelValue'],
  emits: ['update:modelValue'],
  template:
    '<select :value="modelValue" @change="$emit(\'update:modelValue\', $event.target.value)"><slot /></select>',
}

const optionStub = {
  props: ['value'],
  template: '<option :value="value"><slot /></option>',
}

const buttonStub = {
  props: ['type', 'status', 'loading'],
  emits: ['click'],
  template: '<button type="button" :disabled="loading" @click="$emit(\'click\')"><slot /></button>',
}

const alertStub = {
  template: '<div><slot /></div>',
}

const renderView = async () => {
  const pinia = createPinia()
  setActivePinia(pinia)
  useAdminStore(pinia).update({
    id: 'admin-1',
    username: 'admin',
    email: 'admin@example.com',
    name: 'Admin',
    avatar: '',
    status: 'active',
    roles: ['operator'],
    permissions: ['workflow:read', 'workflow:update'],
  })

  mocks.listAdminWorkflows.mockResolvedValue({
    list: [
      {
        id: 'wf-1',
        name: '客服工单分流',
        tool_call_name: 'ticket_router',
        icon: 'robot',
        description: '分流工单到不同队列',
        status: 'published',
        is_public: true,
        created_at: 1710000000,
        updated_at: 1710003600,
      },
    ],
    paginator: { total_record: 1, total_page: 1, current_page: 1, page_size: 20 },
  })

  const wrapper = mount(AdminWorkflowsView, {
    global: {
      plugins: [pinia],
      stubs: {
        'a-input': inputStub,
        'a-select': selectStub,
        'a-option': optionStub,
        'a-button': buttonStub,
        'a-alert': alertStub,
      },
    },
  })

  await flushPromises()
  return wrapper
}

describe('AdminWorkflowsView', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('loads workflows on mount and shows edit actions', async () => {
    const wrapper = await renderView()

    expect(mocks.listAdminWorkflows).toHaveBeenCalledWith({
      search: '',
      status: '',
      current_page: 1,
      page_size: 20,
    })
    expect(wrapper.text()).toContain('客服工单分流')
    expect(wrapper.text()).toContain('ticket_router')
    expect(wrapper.text()).toContain('进入编辑')
  })

  it('shows read-only visibility and store hint without publish/offline actions', async () => {
    const wrapper = await renderView()

    // toggle-public 与 offline 操作已移至资源运营，本页不再渲染
    expect(wrapper.find('[data-testid="workflow-offline-wf-1"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="workflow-visibility-wf-1"]').exists()).toBe(false)
    // 保留公开状态只读展示
    expect(wrapper.text()).toContain('公开')
    // 展示前往资源运营的提示
    expect(wrapper.text()).toContain('资源运营')
  })

  it('navigates to the workflow editor from edit action', async () => {
    const wrapper = await renderView()

    await wrapper.find('[data-testid="workflow-edit-wf-1"]').trigger('click')

    expect(mocks.routerPush).toHaveBeenCalledWith({
      name: 'admin-workflow-edit',
      params: { workflow_id: 'wf-1' },
    })
  })
})
