import { flushPromises, mount } from '@vue/test-utils'
import { ref } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import ConversationSearchView from '../ConversationSearchView.vue'
import * as conversationSearchService from '@/services/conversation-search'
import * as conversationHooks from '@/hooks/use-conversation'

const routerPush = vi.fn()

vi.mock('vue-router', () => ({
  useRouter: () => ({
    push: routerPush,
  }),
}))

vi.mock('@/services/conversation-search', () => ({
  searchConversations: vi.fn(),
}))

vi.mock('@/hooks/use-conversation', () => ({
  useGetRecentConversations: vi.fn(),
  useDeleteConversation: vi.fn(),
  useUpdateConversationName: vi.fn(),
}))

vi.mock('@/views/layouts/components/UpdateConversationNameModal.vue', () => ({
  default: { name: 'UpdateConversationNameModal', template: '<div data-testid="rename-modal" />' },
}))

vi.mock('@/components/recycle-bin/UserRecycleBinDeleteModal.vue', () => ({
  default: {
    name: 'UserRecycleBinDeleteModal',
    props: ['visible', 'title', 'resourceName', 'loading', 'hint'],
    emits: ['update:visible', 'confirm'],
    template:
      '<div data-testid="delete-modal" :data-visible="visible"><button data-testid="delete-confirm" @click="$emit(\'confirm\', 30)" /></div>',
  },
}))

const iconStubs = Object.fromEntries(
  ['search', 'history', 'message', 'right', 'schedule', 'edit', 'delete'].map(name => [
    `icon-${name}`,
    { template: '<span class="icon-stub" />' },
  ]),
)

const buildConversation = (overrides: Record<string, unknown> = {}) => ({
  id: 'conversation-1',
  name: '竞品分析',
  source_type: 'assistant_agent',
  invoke_from: '',
  app_id: '',
  app_name: '',
  agent_name: '',
  message_id: '',
  is_active: true,
  latest_message_at: 1785302400,
  created_at: 1785302400,
  human_message: '帮我分析竞品的定价策略',
  ai_message: '',
  matched_fields: ['name', 'human_message'],
  ...overrides,
})

const mountView = () => {
  return mount(ConversationSearchView, {
    global: { stubs: iconStubs },
  })
}

describe('ConversationSearchView（对齐 search.html 原型 · 真实接口）', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(conversationHooks.useGetRecentConversations).mockReturnValue({
      loading: ref(false),
      conversations: ref([]),
      loadRecentConversations: vi.fn().mockResolvedValue(undefined),
    } as never)
    vi.mocked(conversationHooks.useDeleteConversation).mockReturnValue({
      deleteTarget: ref(null),
      deleteLoading: ref(false),
      handleDeleteConversation: vi.fn(),
      confirmDeleteConversation: vi.fn(),
    } as never)
    vi.mocked(conversationSearchService.searchConversations).mockResolvedValue({
      data: [],
    } as never)
    routerPush.mockClear()
  })

  it('挂载时加载最近会话并在空关键词下展示', async () => {
    const loadRecentConversations = vi.fn().mockResolvedValue(undefined)
    const recent = ref([buildConversation()])
    vi.mocked(conversationHooks.useGetRecentConversations).mockReturnValue({
      loading: ref(false),
      conversations: recent,
      loadRecentConversations,
    } as never)

    const wrapper = mountView()
    await flushPromises()

    expect(loadRecentConversations).toHaveBeenCalledWith(20)
    expect(wrapper.text()).toContain('最近对话')
    expect(wrapper.text()).toContain('竞品分析')
  })

  it('输入关键词后调用真实搜索接口并高亮命中', async () => {
    vi.mocked(conversationSearchService.searchConversations).mockResolvedValue({
      data: [buildConversation({ name: '竞品分析', matched_fields: ['name', 'human_message'] })],
    } as never)

    const wrapper = mountView()
    await flushPromises()

    await wrapper.get('[data-testid="conversation-search-input"]').setValue('竞品')
    await vi.waitFor(() => {
      expect(conversationSearchService.searchConversations).toHaveBeenCalled()
    })
    await flushPromises()

    expect(wrapper.text()).toContain('找到 1 个相关对话')
    expect(wrapper.text()).toContain('竞品分析')
    expect(wrapper.findAll('mark.search-hit').length).toBeGreaterThan(0)
  })

  it('搜索无结果时展示空状态文案', async () => {
    vi.mocked(conversationSearchService.searchConversations).mockResolvedValue({
      data: [],
    } as never)

    const wrapper = mountView()
    await flushPromises()

    await wrapper.get('[data-testid="conversation-search-input"]').setValue('zzz不存在')
    await vi.waitFor(() => {
      expect(conversationSearchService.searchConversations).toHaveBeenCalled()
    })
    await flushPromises()

    expect(wrapper.findAll('[data-testid="conversation-card"]')).toHaveLength(0)
    expect(wrapper.text()).toContain('没有找到相关对话')
  })

  it('标题命中展示匹配来源：标题', async () => {
    vi.mocked(conversationSearchService.searchConversations).mockResolvedValue({
      data: [buildConversation({
        name: '竞品监测计划',
        human_message: '定期整理市场新闻',
        ai_message: '',
        matched_fields: ['name'],
      })],
    } as never)

    const wrapper = mountView()
    await flushPromises()

    await wrapper.get('[data-testid="conversation-search-input"]').setValue('竞品')
    await vi.waitFor(() => {
      expect(conversationSearchService.searchConversations).toHaveBeenCalled()
    })
    await flushPromises()

    expect(wrapper.text()).toContain('匹配来源：标题')
  })

  it('点击删除按钮调用删除 hook 打开确认弹窗', async () => {
    const deleteTarget = ref<{ id: string; name: string } | null>(null)
    const handleDeleteConversation = vi.fn((_id: string, _cb: unknown, name: string) => {
      deleteTarget.value = { id: 'conversation-1', name }
    })
    vi.mocked(conversationHooks.useDeleteConversation).mockReturnValue({
      deleteTarget,
      deleteLoading: ref(false),
      handleDeleteConversation,
      confirmDeleteConversation: vi.fn(),
    } as never)
    vi.mocked(conversationSearchService.searchConversations).mockResolvedValue({
      data: [buildConversation()],
    } as never)

    const wrapper = mountView()
    await flushPromises()

    await wrapper.get('[data-testid="conversation-search-input"]').setValue('竞品')
    await vi.waitFor(() => {
      expect(conversationSearchService.searchConversations).toHaveBeenCalled()
    })
    await flushPromises()

    const card = wrapper.get('[data-testid="conversation-card"]')
    const deleteBtn = card.findAll('button').find(btn => btn.attributes('aria-label') === '删除会话')
    expect(deleteBtn).toBeTruthy()
    await deleteBtn!.trigger('click')
    await flushPromises()

    expect(handleDeleteConversation).toHaveBeenCalled()
    expect(wrapper.get('[data-testid="delete-modal"]').attributes('data-visible')).toBe('true')
  })

  it('点击 assistant_agent 会话卡片跳转首页会话', async () => {
    vi.mocked(conversationSearchService.searchConversations).mockResolvedValue({
      data: [buildConversation({ source_type: 'assistant_agent' })],
    } as never)

    const wrapper = mountView()
    await flushPromises()

    await wrapper.get('[data-testid="conversation-search-input"]').setValue('竞品')
    await vi.waitFor(() => {
      expect(conversationSearchService.searchConversations).toHaveBeenCalled()
    })
    await flushPromises()

    await wrapper.get('[data-testid="conversation-card"]').trigger('click')
    expect(routerPush).toHaveBeenCalledWith(
      expect.objectContaining({ path: '/home', query: { conversation_id: 'conversation-1' } }),
    )
  })

  it('定时任务会话点击不跳转', async () => {
    vi.mocked(conversationSearchService.searchConversations).mockResolvedValue({
      data: [buildConversation({ source_type: 'schedule', invoke_from: 'schedule' })],
    } as never)

    const wrapper = mountView()
    await flushPromises()

    await wrapper.get('[data-testid="conversation-search-input"]').setValue('竞品')
    await vi.waitFor(() => {
      expect(conversationSearchService.searchConversations).toHaveBeenCalled()
    })
    await flushPromises()

    await wrapper.get('[data-testid="conversation-card"]').trigger('click')
    expect(routerPush).not.toHaveBeenCalled()
  })
})
