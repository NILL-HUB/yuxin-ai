import { defineComponent } from 'vue'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'

const mocks = vi.hoisted(() => ({
  createKnowledgeBase: vi.fn(),
  updateKnowledgeBase: vi.fn(),
  deleteKnowledgeBase: vi.fn(),
  getKnowledgeBase: vi.fn(),
  getKnowledgeBasesWithPage: vi.fn(),
  uploadImage: vi.fn(),
  messageSuccess: vi.fn(),
  messageError: vi.fn(),
  messageWarning: vi.fn(),
}))

vi.mock('@/services/knowledge-base', () => ({
  createKnowledgeBase: mocks.createKnowledgeBase,
  updateKnowledgeBase: mocks.updateKnowledgeBase,
  deleteKnowledgeBase: mocks.deleteKnowledgeBase,
  deleteKnowledgeDocument: vi.fn(),
  generateKnowledgeBaseIconPreview: vi.fn(),
  getKnowledgeBase: mocks.getKnowledgeBase,
  getKnowledgeBasesWithPage: mocks.getKnowledgeBasesWithPage,
  getKnowledgeDocument: vi.fn(),
  getKnowledgeDocumentsWithPage: vi.fn(),
  getKnowledgeSegmentsWithPage: vi.fn(),
  hitKnowledgeBase: vi.fn(),
  regenerateKnowledgeBaseIcon: vi.fn(),
  updateKnowledgeSegment: vi.fn(),
  uploadKnowledgeDocument: vi.fn(),
}))

vi.mock('@/services/upload-file', () => ({
  uploadImage: mocks.uploadImage,
  uploadFile: vi.fn(),
}))

vi.mock('@arco-design/web-vue', () => ({
  Message: {
    success: mocks.messageSuccess,
    error: mocks.messageError,
    warning: mocks.messageWarning,
  },
  Modal: { warning: vi.fn() },
  Form: {},
}))

vi.mock('vue-router', async (importOriginal) => {
  const actual = await importOriginal<typeof import('vue-router')>()
  return {
    ...actual,
    useRoute: () => ({ query: {} }),
    useRouter: () => ({ push: vi.fn() }),
  }
})

import ListView from '@/views/space/datasets/ListView.vue'

const slotStub = { template: '<div><slot /></div>' }

const FormStub = defineComponent({
  name: 'AFormStub',
  emits: ['submit'],
  setup(_props, { expose, slots }) {
    expose({
      validate: () => undefined,
      resetFields: () => {},
      validateField: () => {},
    })
    return () => slots.default?.()
  },
})

const SelectStub = defineComponent({
  name: 'ASelectStub',
  inheritAttrs: false,
  props: {
    modelValue: { type: [String, Number], default: undefined },
    options: { type: Array, default: () => [] },
    disabled: { type: Boolean, default: false },
    placeholder: { type: String, default: '' },
  },
  emits: ['update:modelValue'],
  template:
    '<select v-bind="$attrs" :value="modelValue" :disabled="disabled" @change="$emit(\'update:modelValue\', $event.target.value)"><slot /></select>',
})

const globalStubs = {
  'a-modal': slotStub,
  'a-form-item': slotStub,
  'a-input': slotStub,
  'a-textarea': slotStub,
  'a-space': slotStub,
  'a-spin': slotStub,
  'a-card': slotStub,
  'a-avatar': slotStub,
  'a-empty': slotStub,
  'a-drawdown': slotStub,
  'a-dropdown': { template: '<div><slot /><slot name="content" /></div>' },
  'a-doption': { template: '<button type="button" @click="$emit(\'click\')"><slot /></button>' },
  'a-form': FormStub,
  'a-select': SelectStub,
  'a-option': slotStub,
  IconUploadGenerator: slotStub,
  ExternalDataSourceModal: slotStub,
  RecycleBinDeleteModal: slotStub,
  ...Object.fromEntries(
    [
      'icon-book',
      'icon-search',
      'icon-close',
      'icon-cloud',
      'icon-storage',
      'icon-file',
      'icon-link',
      'icon-plus',
      'icon-more',
      'icon-settings',
      'icon-delete',
      'icon-loading',
    ].map((name) => [name, slotStub]),
  ),
}

const listPayload = (baseType: string, partitionMode: string) => ({
  code: 'success',
  message: '',
  data: {
    list: [
      {
        id: 'kb-1',
        name: '素材库',
        icon: '',
        description: '',
        document_count: 0,
        character_count: 0,
        creator_name: '',
        creator_avatar: '',
        base_type: baseType,
        partition_mode: partitionMode,
        updated_at: 0,
        created_at: 0,
      },
    ],
    paginator: { current_page: 1, page_size: 20, total_page: 1, total_record: 1 },
  },
})

const findSelect = (wrapper: ReturnType<typeof mount>, testId: string) =>
  wrapper
    .findAllComponents(SelectStub)
    .find((select) => select.attributes('data-testid') === testId)

describe('datasets ListView 板块类型与分区模式', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    setActivePinia(createPinia())
    mocks.getKnowledgeBasesWithPage.mockResolvedValue(listPayload('mixed', 'none'))
  })

  const mountView = async () => {
    const wrapper = mount(ListView, { global: { stubs: globalStubs } })
    await flushPromises()
    return wrapper
  }

  it('新建弹窗渲染板块类型与分区模式选择器，默认 mixed / none', async () => {
    const wrapper = await mountView()

    const createButton = wrapper
      .findAll('button')
      .find((button) => button.text().includes('新建知识库'))
    expect(createButton).toBeTruthy()
    await createButton!.trigger('click')
    await flushPromises()

    const baseTypeSelect = findSelect(wrapper, 'kb-base-type')
    const partitionSelect = findSelect(wrapper, 'kb-partition-mode')
    expect(baseTypeSelect).toBeTruthy()
    expect(partitionSelect).toBeTruthy()
    expect(baseTypeSelect!.props('modelValue')).toBe('mixed')
    expect(partitionSelect!.props('modelValue')).toBe('none')
  })

  it('新建时提交用户选择的板块类型与分区模式', async () => {
    mocks.createKnowledgeBase.mockResolvedValue({ code: 'success', message: 'ok', data: {} })
    const wrapper = await mountView()

    const createButton = wrapper
      .findAll('button')
      .find((button) => button.text().includes('新建知识库'))
    await createButton!.trigger('click')
    await flushPromises()

    findSelect(wrapper, 'kb-base-type')!.vm.$emit('update:modelValue', 'document')
    findSelect(wrapper, 'kb-partition-mode')!.vm.$emit('update:modelValue', 'date_month')
    await flushPromises()

    const saveButton = wrapper
      .findAll('button')
      .find((button) => button.text().includes('保存'))
    await saveButton!.trigger('click')
    await flushPromises()

    expect(mocks.createKnowledgeBase).toHaveBeenCalledWith(
      expect.objectContaining({ base_type: 'document', partition_mode: 'date_month' }),
    )
  })

  it('编辑已有知识库时回填板块类型/分区模式，并禁用两个选择器', async () => {
    mocks.getKnowledgeBasesWithPage.mockResolvedValue(listPayload('video', 'custom'))
    mocks.getKnowledgeBase.mockResolvedValue({
      code: 'success',
      message: '',
      data: {
        id: 'kb-1',
        name: '素材库',
        icon: '',
        description: '',
        document_count: 0,
        character_count: 0,
        base_type: 'video',
        partition_mode: 'custom',
        updated_at: 0,
        created_at: 0,
      },
    })

    const wrapper = await mountView()

    const settingsButton = wrapper
      .findAll('button')
      .find((button) => button.text().includes('设置'))
    expect(settingsButton).toBeTruthy()
    await settingsButton!.trigger('click')
    await flushPromises()

    const baseTypeSelect = findSelect(wrapper, 'kb-base-type')
    const partitionSelect = findSelect(wrapper, 'kb-partition-mode')
    expect(baseTypeSelect!.props('modelValue')).toBe('video')
    expect(partitionSelect!.props('modelValue')).toBe('custom')
    expect(baseTypeSelect!.attributes('disabled')).toBeDefined()
    expect(partitionSelect!.attributes('disabled')).toBeDefined()
  })
})
