import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'

const mocks = vi.hoisted(() => ({
  getExternalDataSources: vi.fn(),
  createExternalDataSource: vi.fn(),
  syncExternalDataSource: vi.fn(),
  authorizeExternalDataSource: vi.fn(),
  deleteExternalDataSource: vi.fn(),
  messageError: vi.fn(),
  messageSuccess: vi.fn(),
}))

vi.mock('@/services/external-data-source', () => ({
  getExternalDataSources: mocks.getExternalDataSources,
  createExternalDataSource: mocks.createExternalDataSource,
  syncExternalDataSource: mocks.syncExternalDataSource,
  authorizeExternalDataSource: mocks.authorizeExternalDataSource,
  deleteExternalDataSource: mocks.deleteExternalDataSource,
}))

vi.mock('@/stores/credential', () => ({
  useCredentialStore: () => ({ credential: { access_token: 't', expire_at: 9999999999 } }),
}))

vi.mock('@/utils/auth', () => ({
  isCredentialLoggedIn: () => true,
}))

vi.mock('@arco-design/web-vue', () => ({
  Message: {
    error: mocks.messageError,
    success: mocks.messageSuccess,
  },
}))

import ExternalDataSourceModal from '@/views/space/datasets/components/ExternalDataSourceModal.vue'

const slotStub = { template: '<div><slot /></div>' }

const stubs = {
  'a-modal': slotStub,
  'icon-cloud': slotStub,
  'icon-close': slotStub,
  'icon-user': slotStub,
  'icon-loading': slotStub,
  'icon-storage': slotStub,
  'icon-send': slotStub,
  'icon-file': slotStub,
  'icon-github': slotStub,
  'icon-folder': slotStub,
  'icon-common': slotStub,
  'icon-check': slotStub,
  'icon-clock-circle': slotStub,
  'icon-safe': slotStub,
  'icon-sync': slotStub,
  'icon-link': slotStub,
  'icon-exclamation-circle': slotStub,
  'icon-lock': slotStub,
}

const mountModal = async (initialVisible = true) => {
  const wrapper = mount(ExternalDataSourceModal, {
    props: { visible: initialVisible },
    global: { stubs },
  })
  await flushPromises()
  return wrapper
}

describe('ExternalDataSourceModal', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders real data sources from API', async () => {
    mocks.getExternalDataSources.mockResolvedValue({
      code: 'success',
      message: '',
      data: {
        items: [
          {
            id: 's1',
            knowledge_base_id: 'kb1',
            source_type: 'lark',
            source_name: '产品研发知识库',
            authorization_status: 'granted',
            sync_status: 'success',
            sync_cursor: '',
            last_synced_at: '2026-09-03T09:30:00',
            last_error: '',
            config: {},
            created_at: '',
            updated_at: '',
          },
        ],
        total: 1,
      },
    })

    const wrapper = await mountModal()

    expect(mocks.getExternalDataSources).toHaveBeenCalledTimes(1)
    expect(wrapper.text()).toContain('产品研发知识库')
    expect(wrapper.text()).not.toContain('暂无外部数据源')
  })

  it('shows empty state when API returns no data sources', async () => {
    mocks.getExternalDataSources.mockResolvedValue({
      code: 'success',
      message: '',
      data: { items: [], total: 0 },
    })

    const wrapper = await mountModal()

    expect(wrapper.text()).toContain('暂无外部数据源')
  })

  it('creates a data source via real API', async () => {
    mocks.getExternalDataSources.mockResolvedValue({
      code: 'success',
      message: '',
      data: { items: [], total: 0 },
    })
    mocks.createExternalDataSource.mockResolvedValue({ code: 'success', message: '', data: {} })

    const wrapper = await mountModal()
    await wrapper.setProps({ visible: false })
    await wrapper.setProps({ visible: true })
    await flushPromises()
    await wrapper.find('#eds-source-name').setValue('Lark KB')
    await wrapper.find('form.eds-form').trigger('submit')
    await flushPromises()

    expect(mocks.createExternalDataSource).toHaveBeenCalledWith(
      expect.objectContaining({ source_type: 'lark', source_name: 'Lark KB' }),
    )
  })

  it('authorizes a pending source via real API', async () => {
    mocks.getExternalDataSources.mockResolvedValue({
      code: 'success',
      message: '',
      data: {
        items: [
          {
            id: 's2',
            knowledge_base_id: 'kb1',
            source_type: 'notion',
            source_name: 'Notion 空间',
            authorization_status: 'pending',
            sync_status: 'idle',
            sync_cursor: '',
            last_synced_at: null,
            last_error: '',
            config: {},
            created_at: '',
            updated_at: '',
          },
        ],
        total: 1,
      },
    })
    mocks.authorizeExternalDataSource.mockResolvedValue({ code: 'success', message: '', data: {} })

    const wrapper = await mountModal()
    const authorizeButton = wrapper
      .findAll('button')
      .find((button) => button.text().includes('去授权'))
    expect(authorizeButton).toBeTruthy()

    await authorizeButton!.trigger('click')
    await flushPromises()

    expect(mocks.authorizeExternalDataSource).toHaveBeenCalledWith('s2', {})
  })
})
