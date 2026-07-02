import { defineComponent, nextTick, ref } from 'vue'
import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import AdminDatasetDocumentCreateView from '@/views/admin/AdminDatasetDocumentCreateView.vue'

const mocks = vi.hoisted(() => ({
  route: {
    params: { dataset_id: 'dataset-1' },
  },
  handleUploadFile: vi.fn(),
  handleCreateDocuments: vi.fn(),
  loadDocumentsStatus: vi.fn(),
  documentsStatusResult: { value: [] as Record<string, unknown>[] },
  messageError: vi.fn(),
  messageWarning: vi.fn(),
}))

vi.mock('vue-router', async () => {
  const actual = await vi.importActual<typeof import('vue-router')>('vue-router')
  return {
    ...actual,
    useRoute: () => mocks.route,
  }
})

vi.mock('@/hooks/use-upload-file', () => ({
  useUploadFile: () => ({
    loading: { value: false },
    upload_file: { value: {} },
    handleUploadFile: mocks.handleUploadFile,
  }),
}))

vi.mock('@/hooks/use-dataset', () => ({
  useCreateDocuments: () => ({
    loading: ref(false),
    create_documents_result: ref({ batch: 'batch-1' }),
    handleCreateDocuments: mocks.handleCreateDocuments,
  }),
  useGetDocumentsStatus: () => ({
    loading: ref(false),
    documents_status_result: mocks.documentsStatusResult,
    loadDocumentsStatus: mocks.loadDocumentsStatus,
  }),
}))

vi.mock('@arco-design/web-vue', async () => {
  const actual = await vi.importActual<typeof import('@arco-design/web-vue')>(
    '@arco-design/web-vue',
  )

  return {
    ...actual,
    Message: {
      error: mocks.messageError,
      warning: mocks.messageWarning,
    },
  }
})

/**
 * 提供后台导入页测试所需的国际化文案映射，避免依赖真实 i18n 实例。
 */
const messageMap: Record<string, string> = {
  'admin.datasetDocumentImport.back': '返回文档列表',
  'admin.datasetDocumentImport.title': '后台文档导入',
  'admin.datasetDocumentImport.subtitle': '当前数据集：dataset-1',
  'admin.datasetDocumentImport.steps.upload': '上传文件',
  'admin.datasetDocumentImport.steps.segment': '分段设置',
  'admin.datasetDocumentImport.steps.process': '处理状态',
  'admin.datasetDocumentImport.uploadRequired': '请上传需要添加到知识库的文件',
  'admin.datasetDocumentImport.uploadingWarning': '文件正在上传中，请稍等',
  'admin.datasetDocumentImport.invalidFile': '无效文件，请重新选择',
  'admin.datasetDocumentImport.uploadMissingId': '上传成功但未返回文件标识，请重试',
  'admin.datasetDocumentImport.next': '下一步',
  'admin.datasetDocumentImport.previous': '上一步',
  'admin.datasetDocumentImport.submit': '开始创建',
  'admin.datasetDocumentImport.automaticTitle': '自动分段与清洗',
  'admin.datasetDocumentImport.customTitle': '自定义',
  'admin.datasetDocumentImport.separatorLabel': '分隔符',
  'admin.datasetDocumentImport.chunkSizeLabel': '分段长度',
  'admin.datasetDocumentImport.chunkOverlapLabel': '重叠长度',
  'admin.datasetDocumentImport.preProcessLabel': '预处理规则',
  'admin.datasetDocumentImport.preProcessRules.removeExtraSpace': '移除多余空格',
  'admin.datasetDocumentImport.preProcessRules.removeUrlAndEmail': '移除 URL 与邮箱',
  'admin.datasetDocumentImport.processingTitle': '文档处理中',
  'admin.datasetDocumentImport.processingError': '处理失败',
  'admin.datasetDocumentImport.processingCompleted': '处理完成',
  'admin.datasetDocumentImport.processingHint': '文档处理完成后可返回文档列表继续管理',
  'admin.datasetDocumentImport.confirm': '返回文档列表',
}

vi.mock('vue-i18n', () => ({
  useI18n: () => ({
    t: (key: string, params?: { datasetId?: string }) => {
      if (key === 'admin.datasetDocumentImport.subtitle') {
        return `当前数据集：${params?.datasetId ?? ''}`
      }

      return messageMap[key] ?? key
    },
  }),
}))

const UploadStub = defineComponent({
  name: 'AUploadStub',
  props: {
    fileList: {
      type: Array,
      default: () => [],
    },
    customRequest: {
      type: Function,
      default: undefined,
    },
  },
  emits: ['update:file-list'],
  template: `
    <div data-test="upload" :data-has-custom-request="typeof customRequest === 'function' ? 'yes' : 'no'">
      <button
        data-test="set-uploading"
        type="button"
        @click="$emit('update:file-list', [{ uid: 'uploading-1', name: 'draft.txt' }])"
      >
        设置上传中
      </button>
      <button
        data-test="set-uploaded"
        type="button"
        @click="$emit('update:file-list', [{ uid: 'uploaded-1', name: 'done.txt', response: { id: 'file-1' } }])"
      >
        设置上传完成
      </button>
    </div>
  `,
})

const ButtonStub = defineComponent({
  name: 'AButtonStub',
  emits: ['click'],
  template: '<button type="button" @click="$emit(\'click\')"><slot /></button>',
})

const StepsStub = defineComponent({
  name: 'AStepsStub',
  props: {
    current: {
      type: Number,
      default: 1,
    },
  },
  template: '<div data-test="steps" :data-current="String(current)"><slot /></div>',
})

const StepStub = defineComponent({
  name: 'AStepStub',
  template: '<div><slot /></div>',
})

/**
 * 挂载后台文档导入页面，验证后台壳页面标题、返回导航与步骤条是否完整渲染。
 */
const renderView = () => {
  return mount(AdminDatasetDocumentCreateView, {
    global: {
      stubs: {
        'router-link': {
          props: ['to'],
          template: '<a :data-to="JSON.stringify(to)"><slot /></a>',
        },
        'a-button': ButtonStub,
        'a-steps': StepsStub,
        'a-step': StepStub,
        'a-upload': UploadStub,
      },
    },
  })
}

/**
 * 点击后台导入页的“下一步”按钮，避免误触顶部返回按钮。
 */
const clickNextButton = async (wrapper: ReturnType<typeof renderView>) => {
  const nextButton = wrapper
    .findAll('button')
    .find((buttonWrapper) => buttonWrapper.text().includes('下一步'))

  expect(nextButton).toBeDefined()
  await nextButton!.trigger('click')
}

/**
 * 将后台导入页推进到第二步，复用测试中的最小上传完成交互。
 */
const goToSegmentStep = async (wrapper: ReturnType<typeof renderView>) => {
  await wrapper.get('[data-test="set-uploaded"]').trigger('click')
  await nextTick()
  await clickNextButton(wrapper)
}

/**
 * 触发创建动作并等待异步请求完成，便于断言状态查询与轮询行为。
 */
const submitCreateDocuments = async (wrapper: ReturnType<typeof renderView>) => {
  await wrapper.get('[data-test="submit-create"]').trigger('click')
  await flushPromises()
}

describe('AdminDatasetDocumentCreateView', () => {
  afterEach(() => {
    vi.useRealTimers()
  })

  beforeEach(() => {
    mocks.messageError.mockReset()
    mocks.messageWarning.mockReset()
    mocks.handleUploadFile.mockReset()
    mocks.handleCreateDocuments.mockReset()
    mocks.loadDocumentsStatus.mockReset()
    mocks.documentsStatusResult.value = []
  })

  it('renders admin import title and back link', () => {
    const wrapper = renderView()

    expect(wrapper.text()).toContain('后台文档导入')
    expect(wrapper.text()).toContain('当前数据集：dataset-1')
    expect(wrapper.text()).toContain('上传文件')
    expect(wrapper.text()).toContain('分段设置')
    expect(wrapper.text()).toContain('处理状态')
    expect(wrapper.text()).toContain('下一步')
    expect(wrapper.get('[data-test="upload"]').attributes('data-has-custom-request')).toBe('yes')
    expect(wrapper.get('[data-test="steps"]').attributes('data-current')).toBe('1')
    expect(wrapper.html()).toContain('admin-dataset-documents')
  })

  it('blocks next step when no file is uploaded', async () => {
    const wrapper = renderView()

    await clickNextButton(wrapper)

    expect(mocks.messageError).toHaveBeenCalledWith('请上传需要添加到知识库的文件')
    expect(wrapper.get('[data-test="steps"]').attributes('data-current')).toBe('1')
  })

  it('warns when files are still uploading', async () => {
    const wrapper = renderView()

    await wrapper.get('[data-test="set-uploading"]').trigger('click')
    await nextTick()
    await clickNextButton(wrapper)

    expect(mocks.messageWarning).toHaveBeenCalledWith('文件正在上传中，请稍等')
    expect(wrapper.get('[data-test="steps"]').attributes('data-current')).toBe('1')
  })

  it('goes to the second step after all files are uploaded', async () => {
    const wrapper = renderView()

    await wrapper.get('[data-test="set-uploaded"]').trigger('click')
    await nextTick()
    await clickNextButton(wrapper)

    expect(mocks.messageError).not.toHaveBeenCalled()
    expect(mocks.messageWarning).not.toHaveBeenCalled()
    expect(wrapper.get('[data-test="steps"]').attributes('data-current')).toBe('2')
  })

  it('submits custom segmentation payload and stays on step 2', async () => {
    const wrapper = renderView()

    await goToSegmentStep(wrapper)

    expect(wrapper.text()).toContain('自动分段与清洗')
    expect(wrapper.text()).toContain('自定义')

    await wrapper.get('[data-test="select-custom"]').trigger('click')
    await wrapper.get('[data-test="submit-create"]').trigger('click')

    expect(mocks.handleCreateDocuments).toHaveBeenCalledWith(
      'dataset-1',
      expect.objectContaining({
        upload_file_ids: ['file-1'],
        process_type: 'custom',
        rule: expect.objectContaining({
          pre_process_rules: [
            { id: 'remove_extra_space', enabled: false },
            { id: 'remove_url_and_email', enabled: false },
          ],
          segment: expect.objectContaining({
            chunk_size: 500,
            chunk_overlap: 50,
            separators: expect.arrayContaining(['\n\n', '\n']),
          }),
        }),
      }),
    )
    expect(wrapper.get('[data-test="steps"]').attributes('data-current')).toBe('2')
  })

  it('loads document status after successful creation and enters processing step', async () => {
    mocks.documentsStatusResult.value = [
      {
        id: 'doc-1',
        name: 'done.txt',
        size: 128,
        extension: 'txt',
        mime_type: 'text/plain',
        position: 1,
        segment_count: 4,
        completed_segment_count: 1,
        status: 'indexing',
        error: '',
        processing_started_at: 0,
        parsing_completed_at: 0,
        splitting_completed_at: 0,
        indexing_completed_at: 0,
        completed_at: 0,
        stopped_at: 0,
        created_at: 0,
      },
    ]

    const wrapper = renderView()

    await goToSegmentStep(wrapper)
    await submitCreateDocuments(wrapper)

    expect(mocks.handleCreateDocuments).toHaveBeenCalled()
    expect(mocks.loadDocumentsStatus).toHaveBeenCalledWith('dataset-1', 'batch-1')
    expect(wrapper.get('[data-test="steps"]').attributes('data-current')).toBe('3')
    expect(wrapper.text()).toContain('文档处理中')
    expect(wrapper.text()).toContain('done.txt')
    expect(wrapper.text()).toContain('25.00%')
  })

  it('stops polling when all documents are completed', async () => {
    vi.useFakeTimers()

    const processingDocument = {
      id: 'doc-1',
      name: 'done.txt',
      size: 128,
      extension: 'txt',
      mime_type: 'text/plain',
      position: 1,
      segment_count: 4,
      completed_segment_count: 1,
      status: 'indexing',
      error: '',
      processing_started_at: 0,
      parsing_completed_at: 0,
      splitting_completed_at: 0,
      indexing_completed_at: 0,
      completed_at: 0,
      stopped_at: 0,
      created_at: 0,
    }
    const completedDocument = {
      ...processingDocument,
      completed_segment_count: 4,
      status: 'completed',
      completed_at: 1,
    }

    mocks.loadDocumentsStatus.mockImplementation(async () => {
      mocks.documentsStatusResult.value =
        mocks.loadDocumentsStatus.mock.calls.length > 1 ? [completedDocument] : [processingDocument]
    })

    const wrapper = renderView()

    await goToSegmentStep(wrapper)
    await submitCreateDocuments(wrapper)

    expect(vi.getTimerCount()).toBe(1)

    await vi.advanceTimersByTimeAsync(5000)
    await flushPromises()

    expect(mocks.loadDocumentsStatus).toHaveBeenCalledTimes(2)
    expect(wrapper.text()).toContain('处理完成')
    expect(vi.getTimerCount()).toBe(0)
  })

  it('clears polling timer on unmount while documents are still processing', async () => {
    vi.useFakeTimers()

    mocks.loadDocumentsStatus.mockImplementation(async () => {
      mocks.documentsStatusResult.value = [
        {
          id: 'doc-1',
          name: 'done.txt',
          size: 128,
          extension: 'txt',
          mime_type: 'text/plain',
          position: 1,
          segment_count: 4,
          completed_segment_count: 1,
          status: 'indexing',
          error: '',
          processing_started_at: 0,
          parsing_completed_at: 0,
          splitting_completed_at: 0,
          indexing_completed_at: 0,
          completed_at: 0,
          stopped_at: 0,
          created_at: 0,
        },
      ]
    })

    const wrapper = renderView()

    await goToSegmentStep(wrapper)
    await submitCreateDocuments(wrapper)

    expect(vi.getTimerCount()).toBe(1)

    wrapper.unmount()

    expect(vi.getTimerCount()).toBe(0)
  })
})
