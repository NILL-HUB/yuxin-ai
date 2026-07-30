import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import AdminMcpView from '@/views/admin/AdminMcpView.vue'

const mocks = vi.hoisted(() => ({
  listAdminMcpProviders: vi.fn(),
  messageError: vi.fn(),
  routerPush: vi.fn(),
}))

vi.mock('@/services/admin-mcp', () => ({
  listAdminMcpProviders: mocks.listAdminMcpProviders,
  createAdminMcp: vi.fn(),
  deleteAdminMcp: vi.fn(),
}))

vi.mock('vue-router', () => ({
  useRouter: () => ({
    push: mocks.routerPush,
  }),
}))

vi.mock('@/views/space/mcp/components/CreateOrUpdateMcpModal.vue', () => ({
  default: {
    name: 'CreateOrUpdateMcpModal',
    props: ['visible', 'mcpProviderId', 'callback'],
    emits: ['update:visible', 'update:mcpProviderId'],
    template: '<div class="create-or-update-mcp-modal-stub"></div>',
  },
}))

vi.mock('@arco-design/web-vue', async () => {
  const actual = await vi.importActual<typeof import('@arco-design/web-vue')>('@arco-design/web-vue')
  return {
    ...actual,
    Message: {
      error: mocks.messageError,
      success: vi.fn(),
      warning: vi.fn(),
    },
    Modal: { warning: vi.fn() },
  }
})

vi.mock('vue-i18n', () => ({
  useI18n: () => ({
    locale: { value: 'zh-CN' },
    t: (key: string, params?: { count?: number }) =>
      (
        {
          'admin.mcpAdmin.title': 'MCP管理',
          'admin.mcpAdmin.description': '查看平台中的 MCP Provider',
          'admin.mcpAdmin.searchPlaceholder': '搜索 MCP 名称、标签或描述',
          'admin.mcpAdmin.loadFailed': '加载 MCP 列表失败，请重试',
          'admin.mcpAdmin.emptyTitle': '暂无 MCP',
          'admin.mcpAdmin.empty': '当前没有可展示的 MCP Provider',
          'admin.mcpAdmin.emptyFiltered': '没有符合筛选条件的 MCP Provider',
          'admin.mcpAdmin.total': `共 ${params?.count ?? 0} 个 MCP Provider`,
          'admin.mcpAdmin.providerKey': 'Provider Key',
          'admin.mcpAdmin.owner': '创建者',
          'admin.mcpAdmin.toolCount': '工具数',
          'admin.mcpAdmin.transport': '传输协议',
          'admin.mcpAdmin.manageEntry': '前往管理',
          'admin.mcpAdmin.createButton': '新建 MCP',
          'admin.mcpAdmin.importButton': '导入 MCP',
          'admin.mcpAdmin.manageHint': '在管理页可执行发布、删除等操作',
          'admin.mcpAdmin.editButton': '编辑',
          'admin.mcpAdmin.all': '全部',
          'common.actions.search': '搜索',
          'common.actions.refresh': '刷新',
        } satisfies Record<string, string>
      )[key] ?? key,
  }),
}))

const inputStub = {
  props: ['modelValue', 'placeholder'],
  emits: ['update:modelValue'],
  template:
    '<input :value="modelValue" :placeholder="placeholder" @input="$emit(\'update:modelValue\', $event.target.value)" />',
}

const buttonStub = {
  props: ['type', 'status', 'loading'],
  emits: ['click'],
  template: '<button type="button" :disabled="loading" @click="$emit(\'click\')"><slot /></button>',
}

const alertStub = {
  props: ['type', 'showIcon'],
  template: '<div class="a-alert"><slot /></div>',
}

describe('AdminMcpView', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('loads admin mcp providers on mount and supports search', async () => {
    mocks.listAdminMcpProviders.mockResolvedValue({
      list: [
        {
          id: 'provider-1',
          provider_key: 'db:provider-1',
          name: 'weather_mcp',
          label: '天气MCP',
          icon: '',
          background: '#0f172a',
          description: '天气服务',
          category: 'productivity',
          transport: 'streamable_http',
          url: 'https://example.com/mcp',
          command: '',
          headers: [],
          tool_names: [],
          args: [],
          env: {},
          timeout_seconds: 30,
          source_type: 'custom',
          source_key: 'weather_mcp',
          source_url: 'https://example.com/mcp',
          creator_name: 'Alice',
          creator_avatar: '',
          is_public: true,
          is_bindable: true,
          bind_reason: '',
          published_at: 1710000000,
          created_at: 1710000000,
          updated_at: 1710003600,
          tool_count: 3,
          tools: [],
          binding: {},
        },
      ],
      paginator: { total_record: 1, total_page: 1, current_page: 1, page_size: 20 },
    })

    const wrapper = mount(AdminMcpView, {
      global: {
        stubs: {
          'a-input': inputStub,
          'a-button': buttonStub,
          'a-alert': alertStub,
        },
      },
    })

    await flushPromises()

    expect(mocks.listAdminMcpProviders).toHaveBeenCalledWith({
      search_word: '',
      current_page: 1,
      page_size: 50,
      category: '',
    })
    expect(wrapper.text()).toContain('MCP管理')
    expect(wrapper.text()).toContain('天气MCP')
    expect(wrapper.text()).toContain('Alice')
    expect(wrapper.text()).toContain('streamable_http')

    await wrapper.find('input').setValue('weather')
    const searchButton = wrapper.findAll('button').find((b) => b.text().includes('搜索'))
    await searchButton!.trigger('click')
    await flushPromises()

    expect(mocks.listAdminMcpProviders).toHaveBeenLastCalledWith({
      search_word: 'weather',
      current_page: 1,
      page_size: 50,
      category: '',
    })
  })
})
