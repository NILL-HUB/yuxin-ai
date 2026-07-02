import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { useAdminStore } from '@/stores/admin'
import AdminDatasetsView from '@/views/admin/AdminDatasetsView.vue'

const mocks = vi.hoisted(() => ({
  listAdminDatasets: vi.fn(),
  messageError: vi.fn(),
}))

vi.mock('@/services/admin-datasets', () => ({
  listAdminDatasets: mocks.listAdminDatasets,
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
          'admin.datasetsAdmin.title': '知识库管理',
          'admin.datasetsAdmin.description': '查看后台知识库资源与归属信息',
          'admin.datasetsAdmin.searchPlaceholder': '搜索知识库名称、描述或拥有者',
          'admin.datasetsAdmin.emptyTitle': '暂无知识库',
          'admin.datasetsAdmin.empty': '暂无知识库资源',
          'admin.datasetsAdmin.emptyFiltered': '没有符合筛选条件的知识库',
          'admin.datasetsAdmin.loadFailed': '加载知识库列表失败，请重试',
          'admin.datasetsAdmin.owner': '拥有者',
          'admin.datasetsAdmin.documentCount': '文档数',
          'admin.datasetsAdmin.characterCount': '字符数',
          'admin.datasetsAdmin.relatedAppCount': '关联应用',
          'admin.datasetsAdmin.updatedAt': '最近更新',
          'admin.datasetsAdmin.detail': '查看详情',
          'admin.datasetsAdmin.total': `共 ${params?.count ?? 0} 个知识库`,
          'admin.datasetsAdmin.noDescription': '暂无描述',
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

const paginationStub = {
  props: ['current', 'pageSize', 'total'],
  emits: ['change'],
  template: '<nav><slot /></nav>',
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
    permissions: ['dataset:read'],
  })

  mocks.listAdminDatasets.mockResolvedValue({
    list: [
      {
        id: 'dataset-1',
        name: 'CRM知识库',
        icon: 'book',
        description: '客服资料',
        document_count: 8,
        related_app_count: 2,
        character_count: 12000,
        creator_name: 'Alice',
        creator_avatar: 'https://example.com/alice.png',
        upload_at: 1710000000,
        updated_at: 1710003600,
        created_at: 1709990000,
      },
    ],
    paginator: { total_record: 1, total_page: 1, current_page: 1, page_size: 20 },
  })

  const wrapper = mount(AdminDatasetsView, {
    global: {
      plugins: [pinia],
      stubs: {
        'a-input': inputStub,
        'a-button': buttonStub,
        'a-pagination': paginationStub,
      },
    },
  })

  await flushPromises()
  return wrapper
}

describe('AdminDatasetsView', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('loads admin datasets on mount and renders owner and stats', async () => {
    const wrapper = await renderView()

    expect(mocks.listAdminDatasets).toHaveBeenCalledWith({
      search_word: '',
      current_page: 1,
      page_size: 20,
    })
    expect(wrapper.text()).toContain('知识库管理')
    expect(wrapper.text()).toContain('CRM知识库')
    expect(wrapper.text()).toContain('Alice')
    expect(wrapper.text()).toContain('12,000')
    expect(wrapper.text()).toContain('查看详情')
  })
})
