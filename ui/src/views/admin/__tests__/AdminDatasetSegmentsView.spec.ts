import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import AdminDatasetSegmentsView from '@/views/admin/AdminDatasetSegmentsView.vue'

const mocks = vi.hoisted(() => ({
  listAdminDatasetSegments: vi.fn(),
  messageError: vi.fn(),
  route: {
    params: { dataset_id: 'dataset-1', document_id: 'document-1' },
    query: {},
  },
}))

vi.mock('@/services/admin-dataset-segments', () => ({
  listAdminDatasetSegments: mocks.listAdminDatasetSegments,
}))

vi.mock('vue-router', async () => {
  const actual = await vi.importActual<typeof import('vue-router')>('vue-router')
  return {
    ...actual,
    useRoute: () => mocks.route,
  }
})

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
    t: (key: string) =>
      (
        {
          'admin.datasetSegments.title': '知识片段管理',
          'admin.datasetSegments.loadFailed': '加载知识片段失败，请重试',
        } satisfies Record<string, string>
      )[key] ?? key,
  }),
}))

/**
 * 挂载后台知识片段页面并等待首屏异步加载完成。
 */
const renderView = async () => {
  const wrapper = mount(AdminDatasetSegmentsView, {
    global: {
      stubs: {
        'a-empty': true,
        'a-spin': true,
      },
    },
  })

  await flushPromises()
  return wrapper
}

describe('AdminDatasetSegmentsView', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mocks.route.params.dataset_id = 'dataset-1'
    mocks.route.params.document_id = 'document-1'
    mocks.route.query = {}
  })

  it('loads admin segments on mount', async () => {
    mocks.listAdminDatasetSegments.mockResolvedValue({
      list: [],
      paginator: { total_record: 0, total_page: 0, current_page: 1, page_size: 20 },
    })

    await renderView()

    expect(mocks.listAdminDatasetSegments).toHaveBeenCalledWith('dataset-1', 'document-1', {
      current_page: 1,
      page_size: 20,
      search_word: '',
    })
  })
})
