import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import LayoutSidebar from '@/views/layouts/components/LayoutSidebar.vue'
import { HOME_NEW_CONVERSATION_QUERY_KEY } from '@/views/pages/home-new-conversation'

const mocks = vi.hoisted(() => ({
  loggedIn: true,
  adminLoggedIn: false,
  routerPush: vi.fn(),
  routerReplace: vi.fn(),
  route: {
    path: '/space/apps',
    query: {} as Record<string, unknown>,
    params: {} as Record<string, unknown>,
  },
  recentConversations: [] as Record<string, unknown>[],
  recentConversationsRef: undefined as { value: Record<string, unknown>[] } | undefined,
  allRecentConversations: [] as Record<string, unknown>[],
  loadRecentConversations: vi.fn(),
  handleDeleteConversation: vi.fn(),
}))

vi.mock('vue-router', () => ({
  useRoute: () => mocks.route,
  useRouter: () => ({
    push: mocks.routerPush,
    replace: mocks.routerReplace,
  }),
}))

vi.mock('@/stores/credential', () => ({
  useCredentialStore: () => ({
    credential: {},
  }),
}))

vi.mock('@/utils/auth', () => ({
  isCredentialLoggedIn: () => mocks.loggedIn,
}))

vi.mock('@/utils/admin-auth', () => ({
  getStoredAdminCredential: () => ({ access_token: mocks.adminLoggedIn ? 'admin-token' : '', expire_at: mocks.adminLoggedIn ? 1893456000 : 0 }),
  isAdminCredentialLoggedIn: () => mocks.adminLoggedIn,
}))

vi.mock('@/hooks/use-conversation', async () => {
  const { ref } = await import('vue')
  if (!mocks.recentConversationsRef) {
    mocks.recentConversationsRef = ref([])
  }
  return {
    useGetRecentConversations: () => ({
      loading: ref(false),
      conversations: mocks.recentConversationsRef,
      loadRecentConversations: mocks.loadRecentConversations,
    }),
    useDeleteConversation: () => ({
      handleDeleteConversation: mocks.handleDeleteConversation,
    }),
  }
})

const slotStub = {
  template: '<div><slot /><slot name="icon" /><slot name="content" /></div>',
}

const mountSidebar = () => {
  return mount(LayoutSidebar, {
    global: {
      stubs: {
        RouterLink: {
          props: ['to'],
          template: '<a :data-to="to"><slot /></a>',
        },
        'a-button': {
          template: '<button type="button"><slot /><slot name="icon" /></button>',
        },
        'a-dropdown': slotStub,
        'a-doption': slotStub,
        'a-skeleton': slotStub,
        'a-skeleton-line': true,
        UpdateConversationNameModal: true,
        IconHome: true,
        IconHomeFull: true,
        IconSpace: true,
        IconSpaceFull: true,
        IconApps: true,
        IconMessage: true,
        IconMore: true,
        IconEdit: true,
        IconDelete: true,
      },
    },
  })
}

describe('LayoutSidebar home navigation', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mocks.loggedIn = true
    mocks.adminLoggedIn = false
    mocks.route.path = '/space/apps'
    mocks.route.query = {}
    mocks.route.params = {}
    mocks.recentConversations.splice(0, mocks.recentConversations.length)
    if (mocks.recentConversationsRef) {
      mocks.recentConversationsRef.value = []
    }
    mocks.allRecentConversations.splice(0, mocks.allRecentConversations.length)
  })

  it('uses the new conversation entry as the only primary home entry', async () => {
    const wrapper = mountSidebar()
    await flushPromises()

    expect(wrapper.find('[data-testid="sidebar-home-new-conversation"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="sidebar-new-conversation"]').exists()).toBe(true)
  })

  it('starts a new conversation when a logged-in user clicks the primary entry', async () => {
    const wrapper = mountSidebar()
    await flushPromises()

    await wrapper.get('[data-testid="sidebar-new-conversation"]').trigger('click')

    expect(mocks.routerPush).toHaveBeenCalledWith({
      path: '/home',
      query: expect.objectContaining({
        [HOME_NEW_CONVERSATION_QUERY_KEY]: expect.any(String),
      }),
    })
  })

  it('keeps anonymous new-conversation clicks as plain home navigation', async () => {
    mocks.loggedIn = false

    const wrapper = mountSidebar()
    await flushPromises()

    await wrapper.get('[data-testid="sidebar-new-conversation"]').trigger('click')

    expect(mocks.routerPush).toHaveBeenCalledWith('/home')
  })

  it('hides resource orchestration from customer sidebar', async () => {
    const wrapper = mountSidebar()
    await flushPromises()

    expect(wrapper.findAll('a[data-to="/admin/apps"]')).toHaveLength(0)
    expect(wrapper.text()).not.toContain('资源编排')
  })

  it('never shows resource orchestration, even for logged-in admins', async () => {
    mocks.adminLoggedIn = true

    const wrapper = mountSidebar()
    await flushPromises()

    expect(wrapper.findAll('a[data-to="/admin/apps"]')).toHaveLength(0)
    expect(wrapper.text()).not.toContain('资源编排')
  })

  it('does not expose admin console entry in customer sidebar', async () => {
    const wrapper = mountSidebar()
    await flushPromises()

    expect(wrapper.findAll('a[data-to="/admin"]')).toHaveLength(0)
    expect(wrapper.findAll('a[data-to="/admin/login"]')).toHaveLength(0)
    expect(wrapper.text()).not.toContain('管理后台')
    expect(wrapper.text()).not.toContain('管理控制台')
  })

  it('never exposes admin console entry, even for logged-in admins', async () => {
    mocks.adminLoggedIn = true

    const wrapper = mountSidebar()
    await flushPromises()

    expect(wrapper.findAll('a[data-to="/admin"]')).toHaveLength(0)
    expect(wrapper.findAll('a[data-to="/admin/apps"]')).toHaveLength(0)
    expect(wrapper.text()).not.toContain('管理后台')
    expect(wrapper.text()).not.toContain('资源编排')
  })

  it('shows exactly nine entries for regular users', async () => {
    const wrapper = mountSidebar()
    await flushPromises()

    const newConversationButton = wrapper.find('[data-testid="sidebar-new-conversation"]')
    expect(newConversationButton.exists()).toBe(true)
    expect(wrapper.find('[data-testid="sidebar-home-new-conversation"]').exists()).toBe(false)

    const navLinks = wrapper.findAll('a[data-to]')
    expect(navLinks).toHaveLength(9)

    const tos = navLinks.map((link) => link.attributes('data-to'))
    expect(tos).toContain('/search')
    expect(tos).toContain('/memory')
    expect(tos).toContain('/my-knowledge')
    expect(tos).toContain('/external-data-sources')
    expect(tos).toContain('/showcase')
    expect(tos).toContain('/schedules')
    expect(tos).toContain('/membership')
    expect(tos).toContain('/studio')
    expect(tos).toContain('/store/public-apps')

    expect(wrapper.findAll('a[data-to="/store/workflows"]')).toHaveLength(0)
    expect(wrapper.findAll('a[data-to="/store/skills"]')).toHaveLength(0)
    expect(wrapper.findAll('a[data-to="/store/tools"]')).toHaveLength(0)
    expect(wrapper.findAll('a[data-to="/store/mcp"]')).toHaveLength(0)
    expect(wrapper.findAll('a[data-to="/openapi"]')).toHaveLength(0)
    expect(wrapper.findAll('a[data-to="/space/apps"]')).toHaveLength(0)
    expect(wrapper.findAll('a[data-to="/admin"]')).toHaveLength(0)
    expect(wrapper.findAll('a[data-to="/admin/apps"]')).toHaveLength(0)
  })

  it('loads more recent conversations when the sidebar list reaches the bottom', async () => {
    mocks.allRecentConversations = Array.from({ length: 80 }, (_item, index) => ({
      id: `conversation-${index + 1}`,
      name: `Conversation ${index + 1}`,
      source_type: index % 2 === 0 ? 'assistant_agent' : 'app_debugger',
      app_id: index % 2 === 0 ? '' : `app-${index + 1}`,
      message_id: `message-${index + 1}`,
    }))
    mocks.loadRecentConversations.mockImplementation(async (limit: number) => {
      const nextList = mocks.allRecentConversations.slice(0, limit)
      mocks.recentConversationsRef!.value = nextList
    })

    const wrapper = mountSidebar()
    await flushPromises()

    expect(mocks.loadRecentConversations).toHaveBeenCalledWith(20)

    const list = wrapper.get('.recent-conversation-list')
    Object.defineProperty(list.element, 'scrollTop', {
      value: 200,
      writable: true,
      configurable: true,
    })
    Object.defineProperty(list.element, 'clientHeight', {
      value: 200,
      configurable: true,
    })
    Object.defineProperty(list.element, 'scrollHeight', {
      value: 380,
      configurable: true,
    })

    await list.trigger('scroll')
    await flushPromises()

    expect(mocks.loadRecentConversations).toHaveBeenCalledWith(40)
    expect(wrapper.text()).toContain('Conversation 40')

    await list.trigger('scroll')
    await flushPromises()

    Object.defineProperty(list.element, 'scrollTop', {
      value: 120,
      writable: true,
      configurable: true,
    })
    await list.trigger('scroll')
    await flushPromises()

    Object.defineProperty(list.element, 'scrollTop', {
      value: 200,
      writable: true,
      configurable: true,
    })
    await list.trigger('scroll')
    await flushPromises()

    expect(mocks.loadRecentConversations).toHaveBeenCalledWith(60)
    expect(wrapper.text()).toContain('Conversation 60')
    expect(mocks.loadRecentConversations).toHaveBeenCalledTimes(3)

    await list.trigger('scroll')
    await flushPromises()

    expect(mocks.loadRecentConversations).toHaveBeenCalledTimes(3)
    expect(mocks.loadRecentConversations).not.toHaveBeenCalledWith(80)
  })
})
