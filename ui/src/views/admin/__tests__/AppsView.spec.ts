import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { useAdminStore } from '@/stores/admin'
import AppsView from '@/views/admin/AppsView.vue'

const mocks = vi.hoisted(() => ({
  listAdminApps: vi.fn(),
  updateAdminAppBasicInfo: vi.fn(),
  createAdminApp: vi.fn(),
  deleteAdminApp: vi.fn(),
  routerPush: vi.fn(),
  messageSuccess: vi.fn(),
  messageError: vi.fn(),
  messageWarning: vi.fn(),
  modalWarning: vi.fn(),
}))

vi.mock('@/services/admin-apps', () => ({
  listAdminApps: mocks.listAdminApps,
  updateAdminAppBasicInfo: mocks.updateAdminAppBasicInfo,
  createAdminApp: mocks.createAdminApp,
  deleteAdminApp: mocks.deleteAdminApp,
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
      warning: mocks.messageWarning,
    },
    Modal: { warning: mocks.modalWarning },
  }
})

const inputStub = {
  props: ['modelValue', 'placeholder'],
  emits: ['update:modelValue'],
  template:
    '<input :value="modelValue" :placeholder="placeholder" @input="$emit(\'update:modelValue\', $event.target.value)" />',
}

const textareaStub = {
  props: ['modelValue', 'placeholder'],
  emits: ['update:modelValue'],
  template:
    '<textarea :value="modelValue" :placeholder="placeholder" @input="$emit(\'update:modelValue\', $event.target.value)"></textarea>',
}

const buttonStub = {
  props: ['type', 'status', 'loading'],
  emits: ['click'],
  template:
    '<button type="button" :disabled="loading" @click="$emit(\'click\')"><slot /></button>',
}

const renderView = async (permissions = ['app:read', 'app:update']) => {
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
    permissions,
  })

  mocks.listAdminApps.mockResolvedValue({
    list: [
      {
        id: 'app-1',
        name: '编程 Agent',
        icon: '🤖',
        description: '面向编程场景的智能体',
        account_id: 'space-1',
        status: 'published',
        created_at: 1710000000,
        agent_metadata: {
          primary_pool: 'coding',
          risk_level: 'safe',
          routing_priority: 100,
          enabled: true,
        },
      },
    ],
    paginator: { total_record: 1, total_page: 1, current_page: 1, page_size: 20 },
  })

  const wrapper = mount(AppsView, {
    global: {
      plugins: [pinia],
      stubs: {
        'a-input': inputStub,
        'a-textarea': textareaStub,
        'a-button': buttonStub,
        'router-link': { template: '<a><slot /></a>' },
      },
    },
  })

  await flushPromises()
  return wrapper
}

describe('Admin AppsView', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('loads apps on mount and renders app info without metadata editing controls', async () => {
    const wrapper = await renderView()

    expect(mocks.listAdminApps).toHaveBeenCalledWith({
      current_page: 1,
      page_size: 20,
      search: '',
    })
    expect(wrapper.text()).toContain('编程 Agent')
    expect(wrapper.text()).toContain('面向编程场景的智能体')
    // 数据所有权统一后不再有元数据编辑控件
    expect(wrapper.find('[data-test="primary-pool"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="save-metadata"]').exists()).toBe(false)
    // 池治理字段以只读形式展示，并提供跳转提示
    expect(wrapper.text()).toContain('coding')
    const poolLink = wrapper.find('a')
    expect(poolLink.exists()).toBe(true)
    expect(poolLink.text()).toBeTruthy()
  })

  it('navigates to the space app editor from view detail action', async () => {
    const wrapper = await renderView()

    await wrapper.find('[data-testid="app-view-app-1"]').trigger('click')

    expect(mocks.routerPush).toHaveBeenCalledWith({
      name: 'admin-app-edit',
      params: { app_id: 'app-1' },
    })
  })

  it('opens edit basic info modal without immediately calling the service', async () => {
    mocks.updateAdminAppBasicInfo.mockResolvedValue({ id: 'app-1' } as never)
    const wrapper = await renderView()

    await wrapper.find('[data-testid="app-edit-app-1"]').trigger('click')
    await flushPromises()

    // 点击“编辑基本信息”仅打开弹窗，不应立即调用保存接口
    expect(mocks.updateAdminAppBasicInfo).not.toHaveBeenCalled()
  })

  it('hides edit action without app:update permission', async () => {
    const wrapper = await renderView(['app:read'])

    expect(wrapper.find('[data-testid="app-edit-app-1"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="app-view-app-1"]').exists()).toBe(true)
  })
})
