import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { useAdminStore } from '@/stores/admin'
import AdminDatasetDocumentsView from '@/views/admin/AdminDatasetDocumentsView.vue'

const mocks = vi.hoisted(() => ({
  listAdminDatasetDocuments: vi.fn(),
  renameAdminDatasetDocument: vi.fn(),
  updateAdminDatasetDocumentEnabled: vi.fn(),
  deleteAdminDatasetDocument: vi.fn(),
  messageSuccess: vi.fn(),
  messageError: vi.fn(),
  routerPush: vi.fn(),
  route: {
    params: { dataset_id: 'dataset-1' },
    query: {},
  },
}))

vi.mock('@/services/admin-dataset-documents', () => ({
  listAdminDatasetDocuments: mocks.listAdminDatasetDocuments,
}))

vi.mock('@/services/admin-dataset-document-actions', () => ({
  renameAdminDatasetDocument: mocks.renameAdminDatasetDocument,
  updateAdminDatasetDocumentEnabled: mocks.updateAdminDatasetDocumentEnabled,
  deleteAdminDatasetDocument: mocks.deleteAdminDatasetDocument,
}))

vi.mock('vue-router', async () => {
  const actual = await vi.importActual<typeof import('vue-router')>('vue-router')
  return {
    ...actual,
    useRoute: () => mocks.route,
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

vi.mock('vue-i18n', () => ({
  useI18n: () => ({
    t: (key: string, params?: Record<string, string | number>) =>
      (
        {
          'admin.datasetDocuments.title': '知识库文档管理',
          'admin.datasetDocuments.loadFailed': '加载知识库文档失败，请重试',
          'admin.datasetDocuments.actions.rename': '重命名',
          'admin.datasetDocuments.actions.enable': '启用',
          'admin.datasetDocuments.actions.disable': '停用',
          'admin.datasetDocuments.actions.delete': '删除',
          'admin.datasetDocuments.actions.viewSegments': '查看分段',
          'admin.datasetDocuments.importEntry': '导入文档',
          'admin.datasetDocuments.renameModal.title': '重命名文档',
          'admin.datasetDocuments.renameModal.placeholder': '请输入新的文档名称',
          'admin.datasetDocuments.renameModal.confirm': '确认重命名',
          'admin.datasetDocuments.renameModal.cancel': '取消',
          'admin.datasetDocuments.statuses.completed': '已完成',
          'admin.datasetDocuments.statuses.error': '失败',
          'admin.datasetDocuments.statuses.indexing': '处理中',
          'admin.datasetDocuments.errorLabel': '失败原因',
          'admin.datasetDocuments.batch.selected': '已选择 {count} 项',
          'admin.datasetDocuments.batch.enable': '批量启用',
          'admin.datasetDocuments.batch.disable': '批量停用',
          'admin.datasetDocuments.batch.delete': '批量删除',
          'admin.datasetDocuments.feedback.batchDisableSuccess': '批量停用成功',
          'admin.datasetDocuments.feedback.batchDeleteSuccess': '批量删除成功',
          'admin.datasetDocuments.feedback.batchActionFailed': '批量操作失败',
        } satisfies Record<string, string>
      )[key]?.replace('{count}', String(params?.count ?? '')) ?? key,
  }),
}))

/**
 * 构造后台文档测试数据。
 */
const createDocument = (overrides: Partial<Record<string, unknown>> = {}) => ({
  id: 'doc-1',
  name: '员工手册',
  status: 'completed',
  enabled: true,
  character_count: 1200,
  segment_count: 12,
  hit_count: 3,
  created_at: 1710000000,
  updated_at: 1710003600,
  ...overrides,
})

/**
 * 构造后台文档分页响应。
 */
const createListResponse = (documents = [createDocument()]) => ({
  list: documents,
  paginator: {
    total_record: documents.length,
    total_page: 1,
    current_page: 1,
    page_size: 20,
  },
})

/**
 * 构造包含两条后台文档记录的分页响应。
 */
const createTwoDocumentListResponse = () => {
  return createListResponse([
    createDocument(),
    createDocument({
      id: 'doc-2',
      name: '差旅制度',
      enabled: true,
      segment_count: 6,
      hit_count: 1,
    }),
  ])
}

/**
 * 挂载后台知识库文档页面并等待异步数据加载完成。
 */
const renderView = async (permissions = ['dataset:read', 'dataset:update']) => {
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

  const wrapper = mount(AdminDatasetDocumentsView, {
    global: {
      plugins: [pinia],
      stubs: {
        'a-button': {
          emits: ['click'],
          template:
            '<button :data-testid="$attrs[\'data-testid\']" :disabled="$attrs.disabled" @click="$emit(\'click\', $event)"><slot /></button>',
        },
        'a-input': {
          props: ['modelValue'],
          emits: ['update:modelValue'],
          template:
            '<input v-bind="$attrs" :value="modelValue" @input="$emit(\'update:modelValue\', $event.target.value)" />',
        },
        'a-modal': {
          props: ['visible'],
          template: '<div v-if="visible" v-bind="$attrs"><slot /></div>',
        },
        'a-checkbox': {
          props: ['modelValue'],
          emits: ['update:modelValue'],
          template:
            '<input type="checkbox" v-bind="$attrs" :checked="modelValue" @change="$emit(\'update:modelValue\', $event.target.checked)" />',
        },
        'a-empty': true,
        'a-spin': true,
        'router-link': true,
      },
    },
  })

  await flushPromises()
  return wrapper
}

describe('AdminDatasetDocumentsView', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mocks.route.params.dataset_id = 'dataset-1'
    mocks.route.query = {}
    mocks.routerPush.mockResolvedValue(undefined)
  })

  it('loads admin documents on mount', async () => {
    mocks.listAdminDatasetDocuments.mockResolvedValue(createListResponse([]))

    await renderView()

    expect(mocks.listAdminDatasetDocuments).toHaveBeenCalledWith('dataset-1', {
      current_page: 1,
      page_size: 20,
      search_word: '',
    })
  })

  it('shows action buttons for each document', async () => {
    mocks.listAdminDatasetDocuments.mockResolvedValue(createListResponse())

    const wrapper = await renderView()

    expect(wrapper.text()).toContain('重命名')
    expect(wrapper.text()).toContain('停用')
    expect(wrapper.text()).toContain('删除')
    expect(wrapper.text()).toContain('查看分段')
  })

  it('renames document and reloads list', async () => {
    mocks.listAdminDatasetDocuments.mockResolvedValue(createListResponse())
    mocks.renameAdminDatasetDocument.mockResolvedValue({ message: 'ok' })

    const wrapper = await renderView()
    const initialLoadCount = mocks.listAdminDatasetDocuments.mock.calls.length

    await wrapper.get('[data-testid="document-rename-doc-1"]').trigger('click')
    await wrapper.get('[data-testid="document-rename-input"]').setValue('员工手册-新')
    await wrapper.get('[data-testid="document-rename-confirm"]').trigger('click')
    await flushPromises()

    expect(mocks.renameAdminDatasetDocument).toHaveBeenCalledWith('dataset-1', 'doc-1', '员工手册-新')
    expect(mocks.listAdminDatasetDocuments.mock.calls.length).toBe(initialLoadCount + 1)
  })

  it('toggles document enabled state and reloads list', async () => {
    mocks.listAdminDatasetDocuments.mockResolvedValue(createListResponse())
    mocks.updateAdminDatasetDocumentEnabled.mockResolvedValue({ message: 'ok' })

    const wrapper = await renderView()
    const initialLoadCount = mocks.listAdminDatasetDocuments.mock.calls.length

    await wrapper.get('[data-testid="document-toggle-doc-1"]').trigger('click')
    await flushPromises()

    expect(mocks.updateAdminDatasetDocumentEnabled).toHaveBeenCalledWith('dataset-1', 'doc-1', false)
    expect(mocks.listAdminDatasetDocuments.mock.calls.length).toBe(initialLoadCount + 1)
  })

  it('deletes document and reloads list', async () => {
    mocks.listAdminDatasetDocuments.mockResolvedValue(createListResponse())
    mocks.deleteAdminDatasetDocument.mockResolvedValue({ message: 'ok' })

    const wrapper = await renderView()
    const initialLoadCount = mocks.listAdminDatasetDocuments.mock.calls.length

    await wrapper.get('[data-testid="document-delete-doc-1"]').trigger('click')
    await flushPromises()

    expect(mocks.deleteAdminDatasetDocument).toHaveBeenCalledWith('dataset-1', 'doc-1')
    expect(mocks.listAdminDatasetDocuments.mock.calls.length).toBe(initialLoadCount + 1)
  })

  it('navigates to document segments view', async () => {
    mocks.listAdminDatasetDocuments.mockResolvedValue(createListResponse())

    const wrapper = await renderView()

    await wrapper.get('[data-testid="document-segments-doc-1"]').trigger('click')

    expect(mocks.routerPush).toHaveBeenCalledWith({
      name: 'admin-dataset-segments',
      params: {
        dataset_id: 'dataset-1',
        document_id: 'doc-1',
      },
    })
  })

  it('shows batch action bar when documents are selected', async () => {
    mocks.listAdminDatasetDocuments.mockResolvedValue(createListResponse())

    const wrapper = await renderView()

    await wrapper.get('[data-testid="document-select-doc-1"]').setValue(true)
    await flushPromises()

    expect(wrapper.text()).toContain('已选择 1 项')
    expect(wrapper.text()).toContain('批量停用')
    expect(wrapper.text()).toContain('批量删除')
  })

  it('runs batch disable against selected documents', async () => {
    mocks.listAdminDatasetDocuments.mockResolvedValue(createTwoDocumentListResponse())
    mocks.updateAdminDatasetDocumentEnabled.mockResolvedValue({ message: 'ok' })

    const wrapper = await renderView()

    await wrapper.get('[data-testid="document-select-doc-1"]').setValue(true)
    await wrapper.get('[data-testid="document-select-doc-2"]').setValue(true)
    await wrapper.get('[data-testid="documents-batch-disable"]').trigger('click')
    await flushPromises()

    expect(mocks.updateAdminDatasetDocumentEnabled).toHaveBeenCalledTimes(2)
    expect(mocks.updateAdminDatasetDocumentEnabled).toHaveBeenNthCalledWith(1, 'dataset-1', 'doc-1', false)
    expect(mocks.updateAdminDatasetDocumentEnabled).toHaveBeenNthCalledWith(2, 'dataset-1', 'doc-2', false)
  })

  it('runs batch delete against selected documents', async () => {
    mocks.listAdminDatasetDocuments.mockResolvedValue(createTwoDocumentListResponse())
    mocks.deleteAdminDatasetDocument.mockResolvedValue({ message: 'ok' })

    const wrapper = await renderView()

    await wrapper.get('[data-testid="document-select-doc-1"]').setValue(true)
    await wrapper.get('[data-testid="document-select-doc-2"]').setValue(true)
    await wrapper.get('[data-testid="documents-batch-delete"]').trigger('click')
    await flushPromises()

    expect(mocks.deleteAdminDatasetDocument).toHaveBeenCalledTimes(2)
    expect(mocks.deleteAdminDatasetDocument).toHaveBeenNthCalledWith(1, 'dataset-1', 'doc-1')
    expect(mocks.deleteAdminDatasetDocument).toHaveBeenNthCalledWith(2, 'dataset-1', 'doc-2')
  })

  it('shows error label for failed documents', async () => {
    mocks.listAdminDatasetDocuments.mockResolvedValue(
      createListResponse([
        createDocument({
          name: '失败文档',
          status: 'error',
          enabled: false,
          character_count: 0,
          segment_count: 0,
          hit_count: 0,
          error: '向量索引失败',
        }),
      ]),
    )

    const wrapper = await renderView()

    expect(wrapper.text()).toContain('失败原因')
    expect(wrapper.text()).toContain('向量索引失败')
  })

  it('hides write actions and selection without dataset:update permission', async () => {
    mocks.listAdminDatasetDocuments.mockResolvedValue(createListResponse())

    const wrapper = await renderView(['dataset:read'])

    expect(wrapper.text()).not.toContain('导入文档')
    expect(wrapper.find('[data-testid="document-select-doc-1"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="document-rename-doc-1"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="document-toggle-doc-1"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="document-delete-doc-1"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="document-segments-doc-1"]').exists()).toBe(true)
  })
})
