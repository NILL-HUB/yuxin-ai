import { defineComponent } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, shallowMount } from '@vue/test-utils'
import McpListView from '@/views/store/mcp/ListView.vue'

const mocks = vi.hoisted(() => ({
  getPublicMcpCategories: vi.fn(),
  getPublicMcpProvidersWithPage: vi.fn(),
  getPublicMcpProvider: vi.fn(),
}))

vi.mock('@/services/mcp', () => ({
  getPublicMcpCategories: mocks.getPublicMcpCategories,
  getPublicMcpProvidersWithPage: mocks.getPublicMcpProvidersWithPage,
  getPublicMcpProvider: mocks.getPublicMcpProvider,
}))

const buttonStub = defineComponent({
  name: 'ArcoButtonStub',
  emits: ['click'],
  template: '<button type="button" v-bind="$attrs" @click="$emit(\'click\', $event)"><slot /></button>',
})

const globalStubs = {
  'a-spin': {
    template: '<div><slot /></div>',
  },
  'a-avatar': {
    template: '<div><slot /></div>',
  },
  'a-button': buttonStub,
  'a-tag': {
    template: '<span><slot /></span>',
  },
  'a-card': {
    template: '<div><slot /></div>',
  },
  'a-col': {
    template: '<div><slot /></div>',
  },
  'a-empty': {
    template: '<div><slot /></div>',
  },
  'a-row': {
    template: '<div><slot /></div>',
  },
  'a-drawer': {
    template: '<div><slot /></div>',
  },
  'a-input-search': {
    template: '<input />',
  },
  'card-grid-skeleton': {
    template: '<div />',
  },
  'resource-card-description': {
    template: '<div />',
  },
  'icon-computer': {
    template: '<span data-icon="computer" />',
  },
  'icon-close': {
    template: '<span />',
  },
  'icon-more': {
    template: '<span />',
  },
}

describe('store mcp list', () => {
  beforeEach(() => {
    vi.clearAllMocks()

    mocks.getPublicMcpCategories.mockResolvedValue({
      data: {
        categories: [
          { id: 'general', name: '通用', priority: 1, background: '#DBEAFE' },
          { id: 'coding', name: '编程工具', priority: 3, background: '#E0E7FF' },
          { id: 'content_creation', name: '内容创作', priority: 4, background: '#FEE2E2' },
          { id: 'media', name: '媒体音视频', priority: 5, background: '#FCE7F3' },
          { id: 'productivity', name: '效率工具', priority: 2, background: '#DCFCE7' },
          { id: 'data_analysis', name: '数据分析', priority: 6, background: '#EDE9FE' },
          { id: 'observability', name: '可观测运维', priority: 7, background: '#FEF3C7' },
          { id: 'other', name: '其他', priority: 99, background: '#E5E7EB' },
        ],
      },
    })

    mocks.getPublicMcpProvidersWithPage.mockResolvedValue({
      data: {
        list: [
          {
            provider_key: 'weather-mcp',
            name: 'weather-mcp',
            label: '天气 MCP',
            icon: '',
            background: '#DBEAFE',
            description: '查询实时天气和预报',
            category: 'general',
            transport: 'streamable_http',
            url: 'https://example.com/mcp',
            command: '',
            headers: [],
            tool_names: [],
            args: [],
            env: {},
            timeout_seconds: 30,
            source_type: 'catalog',
            source_key: 'weather',
            source_url: 'https://example.com/weather',
            creator_name: 'OpenAI',
            creator_avatar: '',
            is_public: true,
            is_bindable: true,
            bind_reason: '',
            published_at: 1700000000,
            created_at: 1700000000,
            updated_at: 1700000000,
            tool_count: 2,
            tools: [],
            binding: {},
          },
        ],
        paginator: {
          current_page: 1,
          page_size: 50,
          total_page: 1,
          total_record: 1,
        },
      },
    })

    mocks.getPublicMcpProvider.mockResolvedValue({
      data: {
        provider_key: 'weather-mcp',
        name: 'weather-mcp',
        label: '天气 MCP',
        icon: '',
        background: '#DBEAFE',
        description: '查询实时天气和预报',
        category: 'general',
        transport: 'streamable_http',
        url: 'https://example.com/mcp',
        command: '',
        headers: [],
        tool_names: [],
        args: [],
        env: {},
        timeout_seconds: 30,
        source_type: 'catalog',
        source_key: 'weather',
        source_url: 'https://example.com/weather',
        creator_name: 'OpenAI',
        creator_avatar: '',
        is_public: true,
        is_bindable: true,
        bind_reason: '',
        published_at: 1700000000,
        created_at: 1700000000,
        updated_at: 1700000000,
        tool_count: 2,
        tools: [],
        binding: {},
      },
    })
  })

  it('renders store mcp list without a create button or create modal', async () => {
    const wrapper = shallowMount(McpListView, {
      global: {
        stubs: globalStubs,
      },
    })

    await flushPromises()

    expect(mocks.getPublicMcpCategories).toHaveBeenCalledTimes(1)
    expect(mocks.getPublicMcpProvidersWithPage).toHaveBeenCalledTimes(1)
    expect(wrapper.text()).toContain('MCP 广场')
    expect(wrapper.text()).not.toContain('公开免费 MCP 目录')
    expect(wrapper.text()).not.toContain('general')
    expect(wrapper.text()).not.toContain('仅查看')
    expect(wrapper.text()).not.toContain('天气 MCP 草稿')
    expect(wrapper.text()).not.toContain('当前环境不支持该 MCP')
    expect(wrapper.find('[data-icon="computer"]').exists()).toBe(true)

    ;['通用', '编程工具', '内容创作', '媒体音视频', '效率工具', '数据分析', '可观测运维', '其他'].forEach((category) => {
      expect(wrapper.text()).toContain(category)
    })

    expect(wrapper.find('[data-testid="store-mcp-create-button"]').exists()).toBe(false)
  })
})
