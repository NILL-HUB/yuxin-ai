import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import ToolsView from '@/views/admin/ToolsView.vue'

const mocks = vi.hoisted(() => ({
  listAdminApiTools: vi.fn(),
  messageError: vi.fn(),
}))

vi.mock('@/services/admin-tools', () => ({
  listAdminApiTools: mocks.listAdminApiTools,
  createAdminApiTool: vi.fn(),
  getAdminApiTool: vi.fn(),
  updateAdminApiTool: vi.fn(),
  deleteAdminApiTool: vi.fn(),
}))

vi.mock('@arco-design/web-vue', async () => {
  const actual = await vi.importActual<typeof import('@arco-design/web-vue')>('@arco-design/web-vue')
  return {
    ...actual,
    Message: { error: mocks.messageError, success: vi.fn(), warning: vi.fn() },
    Modal: { warning: vi.fn() },
  }
})

vi.mock('@/hooks/use-tool', () => ({
  useGenerateIconPreview: () => ({ loading: { value: false }, handleGenerateIconPreview: vi.fn() }),
  useValidateOpenAPISchema: () => ({ handleValidateOpenAPISchema: vi.fn() }),
}))

vi.mock('@/hooks/use-upload-file', () => ({
  useUploadImage: () => ({ image_url: { value: '' }, handleUploadImage: vi.fn() }),
}))

vi.mock('vue-i18n', () => ({
  useI18n: () => ({
    t: (key: string, params?: { count?: number }) =>
      (
        {
          'admin.toolsAdmin.title': 'API工具管理',
          'admin.toolsAdmin.description': '管理 API Tool Provider 的创建、编辑与删除',
          'admin.toolsAdmin.searchPlaceholder': '搜索工具名称',
          'admin.toolsAdmin.empty': '当前没有可展示的 API Tool Provider',
          'admin.toolsAdmin.emptyFiltered': '没有符合筛选条件的 API Tool Provider',
          'admin.toolsAdmin.createButton': '创建 API 工具',
          'admin.toolsAdmin.editButton': '编辑',
          'admin.toolsAdmin.deleteButton': '删除',
          'admin.toolsAdmin.schemaParsed': '已解析',
          'admin.toolsAdmin.schemaEmpty': '未配置',
          'admin.toolsAdmin.governanceLink': '进入完整治理中心',
          'admin.toolsAdmin.total': `共 ${params?.count ?? 0} 个 API 工具`,
          'admin.toolsAdmin.loadFailed': '加载 API 工具列表失败，请重试',
          'admin.toolsAdmin.columns.name': '工具名称',
          'admin.toolsAdmin.columns.description': '描述',
          'admin.toolsAdmin.columns.schemaStatus': 'OpenAPI Schema',
          'admin.toolsAdmin.columns.toolCount': '工具数量',
          'admin.toolsAdmin.columns.createdAt': '创建时间',
          'admin.toolsAdmin.columns.actions': '操作',
          'common.actions.search': '搜索',
          'common.actions.refresh': '刷新',
          'common.actions.cancel': '取消',
          'common.actions.save': '保存',
          'space.tools.createTitle': '新建插件',
          'space.tools.updateTitle': '更新插件',
          'space.tools.iconPlaceholder': '插件',
          'space.tools.iconRequired': '插件图标不能为空',
          'space.tools.pluginName': '插件名称',
          'space.tools.pluginNameRequired': '插件名称不能为空',
          'space.tools.pluginNamePlaceholder': '请输入插件名称',
          'space.tools.openapiSchemaRequired': 'OpenAPI Schema 不能为空',
          'space.tools.openapiSchemaPlaceholder': '在此处输入或粘贴 OpenAPI Schema(JSON)',
          'space.tools.headerKeyPlaceholder': '请输入请求头键名',
          'space.tools.headerValuePlaceholder': '请输入请求头键值内容',
          'space.tools.addHeader': '增加参数',
          'space.tools.columns.key': 'Key',
          'space.tools.columns.value': 'Value',
          'space.tools.columns.action': '操作',
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

const tableStub = {
  props: ['columns', 'data', 'loading', 'pagination', 'rowKey', 'scroll'],
  template:
    '<div class="table-stub"><div v-for="row in data" :key="row.id" class="row">{{ row.name }}</div></div>',
}

const modalStub = {
  props: ['visible', 'width', 'footer', 'hideTitle'],
  template: '<div v-if="visible"><slot /></div>',
}

describe('Admin ToolsView', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('loads api tool providers on mount and supports keyword search', async () => {
    mocks.listAdminApiTools.mockResolvedValue({
      list: [
        {
          id: 'provider-1',
          name: '天气查询',
          icon: '',
          description: '天气工具',
          headers: [],
          tools: [{ name: 'getCurrentWeather', description: 'get weather' }],
          creator_name: 'Alice',
          creator_avatar: '',
          updated_at: 1710003600,
          created_at: 1710000000,
        },
      ],
      paginator: { total_record: 1, total_page: 1, current_page: 1, page_size: 20 },
    })

    const wrapper = mount(ToolsView, {
      global: {
        stubs: {
          'a-input': inputStub,
          'a-button': buttonStub,
          'a-table': tableStub,
          'a-modal': modalStub,
          IconUploadGenerator: true,
        },
      },
    })

    await flushPromises()

    expect(mocks.listAdminApiTools).toHaveBeenCalledWith({
      current_page: 1,
      page_size: 20,
      search_word: '',
    })
    expect(wrapper.text()).toContain('API工具管理')
    expect(wrapper.text()).toContain('天气查询')
    expect(wrapper.text()).toContain('进入完整治理中心')
    expect(wrapper.text()).toContain('共 1 个 API 工具')

    await wrapper.find('input').setValue('weather')
    await wrapper.findAll('button')[0].trigger('click')
    await flushPromises()

    expect(mocks.listAdminApiTools).toHaveBeenLastCalledWith({
      current_page: 1,
      page_size: 20,
      search_word: 'weather',
    })
  })
})
