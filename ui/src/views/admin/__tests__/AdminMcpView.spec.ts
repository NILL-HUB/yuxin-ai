import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import AdminMcpView from '@/views/admin/AdminMcpView.vue'

const mocks = vi.hoisted(() => ({
  listAdminMcpProviders: vi.fn(),
  messageError: vi.fn(),
}))

vi.mock('@/services/admin-mcp', () => ({
  listAdminMcpProviders: mocks.listAdminMcpProviders,
}))

vi.mock('@arco-design/web-vue', async () => {
  const actual = await vi.importActual<typeof import('@arco-design/web-vue')>('@arco-design/web-vue')
  return {
    ...actual,
    Message: {
      error: mocks.messageError,
    },
  }
})

vi.mock('vue-i18n', () => ({
  useI18n: () => ({
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
        },
      },
    })

    await flushPromises()

    expect(mocks.listAdminMcpProviders).toHaveBeenCalledWith({
      search_word: '',
      current_page: 1,
      page_size: 20,
      category: '',
    })
    expect(wrapper.text()).toContain('MCP管理')
    expect(wrapper.text()).toContain('天气MCP')
    expect(wrapper.text()).toContain('Alice')
    expect(wrapper.text()).toContain('streamable_http')
    expect(wrapper.text()).toContain('db:provider-1')

    await wrapper.find('input').setValue('weather')
    await wrapper.findAll('button')[0].trigger('click')
    await flushPromises()

    expect(mocks.listAdminMcpProviders).toHaveBeenLastCalledWith({
      search_word: 'weather',
      current_page: 1,
      page_size: 20,
      category: '',
    })
  })
})
