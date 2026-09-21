import { defineComponent } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, shallowMount } from '@vue/test-utils'
import McpListView from '@/views/store/mcp/ListView.vue'

const mocks = vi.hoisted(() => ({
  getPublicMcpCategories: vi.fn(),
  getPublicMcpProvidersWithPage: vi.fn(),
  getPublicMcpProvider: vi.fn(),
  publishAdminMcp: vi.fn(),
  unpublishAdminMcp: vi.fn(),
}))

vi.mock('@/services/mcp', () => ({
  getPublicMcpCategories: mocks.getPublicMcpCategories,
  getPublicMcpProvidersWithPage: mocks.getPublicMcpProvidersWithPage,
  getPublicMcpProvider: mocks.getPublicMcpProvider,
}))

vi.mock('@/services/admin-mcp', () => ({
  publishAdminMcp: mocks.publishAdminMcp,
  unpublishAdminMcp: mocks.unpublishAdminMcp,
}))

vi.mock('@/stores/admin', () => ({
  useAdminStore: () => ({
    hasPermission: (perm: string) => perm === 'mcp:manage',
  }),
}))

const buttonStub = defineComponent({
  name: 'ArcoButtonStub',
  emits: ['click'],
  template: '<button type="button" v-bind="$attrs" @click="$emit(\'click\', $event)"><slot /></button>',
})

const globalStubs = {
  'a-spin': { template: '<div><slot /></div>' },
  'a-avatar': { template: '<div><slot /></div>' },
  'a-button': buttonStub,
  'a-tag': { template: '<span><slot /></span>' },
  'a-card': { template: '<div><slot /></div>' },
  'a-col': { template: '<div><slot /></div>' },
  'a-empty': { template: '<div><slot /></div>' },
  'a-row': { template: '<div><slot /></div>' },
  'a-drawer': { template: '<div><slot /></div>' },
  'a-input-search': { template: '<input />' },
  'card-grid-skeleton': { template: '<div />' },
  'resource-card-description': { template: '<div />' },
  'icon-computer': { template: '<span data-icon="computer" />' },
}

const provider = (key: string, is_public: boolean, label: string) => ({
  id: `uuid-${key}`,
  provider_key: key,
  name: key,
  label,
  icon: '',
  background: '#DBEAFE',
  description: `${label} 描述`,
  category: 'general',
  transport: 'streamable_http',
  url: '',
  command: '',
  headers: [],
  tool_names: [],
  args: [],
  env: {},
  timeout_seconds: 30,
  source_type: 'catalog',
  source_key: key,
  source_url: '',
  creator_name: 'OpenAI',
  creator_avatar: '',
  is_public,
  is_bindable: true,
  bind_reason: '',
  published_at: 1700000000,
  created_at: 1700000000,
  updated_at: 1700000000,
  tool_count: 2,
  tools: [],
  binding: {},
})

describe('store mcp list admin-mode publish/unpublish (UX-3)', () => {
  beforeEach(() => {
    vi.clearAllMocks()

    mocks.getPublicMcpCategories.mockResolvedValue({
      data: { categories: [{ id: 'general', name: '通用', priority: 1, background: '#DBEAFE' }] },
    })
    mocks.getPublicMcpProvidersWithPage.mockResolvedValue({
      data: {
        list: [provider('draft-mcp', false, '草稿 MCP'), provider('online-mcp', true, '上线 MCP')],
        paginator: { current_page: 1, page_size: 50, total_page: 1, total_record: 2 },
      },
    })
    mocks.getPublicMcpProvider.mockResolvedValue({ data: provider('draft-mcp', false, '草稿 MCP') })
    mocks.publishAdminMcp.mockResolvedValue({ data: {} })
    mocks.unpublishAdminMcp.mockResolvedValue({ data: {} })
  })

  it('adminMode render publish button for unpublished provider, and unpublish button for published provider', async () => {
    const wrapper = shallowMount(McpListView, {
      props: { adminMode: true },
      global: { stubs: globalStubs },
    })
    await flushPromises()

    expect(mocks.getPublicMcpProvidersWithPage).toHaveBeenCalledTimes(1)
    expect(wrapper.find('[data-testid="store-mcp-publish-draft-mcp"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="store-mcp-unpublish-draft-mcp"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="store-mcp-unpublish-online-mcp"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="store-mcp-publish-online-mcp"]').exists()).toBe(false)
  })

  it('adminMode publish button calls publishAdminMcp with provider id and reloads list', async () => {
    const wrapper = shallowMount(McpListView, {
      props: { adminMode: true },
      global: { stubs: globalStubs },
    })
    await flushPromises()

    await wrapper.find('[data-testid="store-mcp-publish-draft-mcp"]').trigger('click')
    await flushPromises()

    expect(mocks.publishAdminMcp).toHaveBeenCalledTimes(1)
    expect(mocks.publishAdminMcp).toHaveBeenCalledWith('uuid-draft-mcp')
    expect(mocks.getPublicMcpProvidersWithPage).toHaveBeenCalledTimes(2)
  })

  it('adminMode unpublish button calls unpublishAdminMcp with provider id and reloads list', async () => {
    const wrapper = shallowMount(McpListView, {
      props: { adminMode: true },
      global: { stubs: globalStubs },
    })
    await flushPromises()

    await wrapper.find('[data-testid="store-mcp-unpublish-online-mcp"]').trigger('click')
    await flushPromises()

    expect(mocks.unpublishAdminMcp).toHaveBeenCalledTimes(1)
    expect(mocks.unpublishAdminMcp).toHaveBeenCalledWith('uuid-online-mcp')
    expect(mocks.getPublicMcpProvidersWithPage).toHaveBeenCalledTimes(2)
  })

  it('user mode (adminMode=false) renders no publish/unpublish buttons', async () => {
    const wrapper = shallowMount(McpListView, {
      props: {},
      global: { stubs: globalStubs },
    })
    await flushPromises()

    expect(wrapper.find('[data-testid^="store-mcp-publish-"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid^="store-mcp-unpublish-"]').exists()).toBe(false)
  })
})