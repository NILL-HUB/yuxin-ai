import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import AdminSkillsView from '@/views/admin/AdminSkillsView.vue'

const mocks = vi.hoisted(() => ({
  listAdminSkills: vi.fn(),
  messageError: vi.fn(),
  routerPush: vi.fn(),
}))

vi.mock('@/services/admin-skills', () => ({
  listAdminSkills: mocks.listAdminSkills,
}))

vi.mock('vue-router', () => ({
  useRouter: () => ({
    push: mocks.routerPush,
  }),
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
          'admin.skillsAdmin.title': 'Skills管理',
          'admin.skillsAdmin.description': '查看平台 Skills 目录',
          'admin.skillsAdmin.searchPlaceholder': '搜索 Skill 名称、分类或描述',
          'admin.skillsAdmin.loadFailed': '加载 Skills 列表失败，请重试',
          'admin.skillsAdmin.emptyTitle': '暂无 Skills',
          'admin.skillsAdmin.empty': '当前没有可展示的 Skills',
          'admin.skillsAdmin.emptyFiltered': '没有符合筛选条件的 Skills',
          'admin.skillsAdmin.total': `共 ${params?.count ?? 0} 个 Skill`,
          'admin.skillsAdmin.sourceKey': 'Source Key',
          'admin.skillsAdmin.category': '分类',
          'admin.skillsAdmin.executorType': '执行方式',
          'admin.skillsAdmin.toolCount': '工具数',
          'admin.skillsAdmin.browseStore': '前往商店浏览',
          'admin.skillsAdmin.manageHint': '在商店页可查看与安装 Skill 包',
          'common.actions.search': '搜索',
          'common.actions.refresh': '刷新',
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

const alertStub = {
  props: ['type', 'showIcon'],
  template: '<div class="a-alert"><slot /></div>',
}

describe('AdminSkillsView', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('loads admin skills on mount and supports search', async () => {
    mocks.listAdminSkills.mockResolvedValue({
      list: [
        {
          id: 'skill-1',
          source_key: 'frontend-skill',
          name: 'frontend-skill',
          label: 'Frontend Skill',
          icon: '',
          description: 'Build strong frontend interfaces',
          readme: '',
          category: 'frontend',
          tags: [],
          capabilities: {},
          executor_type: 'prompt',
          tool_count: 0,
          tools: [],
          created_at: 1710000000,
          updated_at: 1710003600,
        },
      ],
      paginator: { total_record: 1, total_page: 1, current_page: 1, page_size: 20 },
    })

    const wrapper = mount(AdminSkillsView, {
      global: {
        stubs: {
          'a-input': inputStub,
          'a-button': buttonStub,
          'a-alert': alertStub,
        },
      },
    })

    await flushPromises()

    expect(mocks.listAdminSkills).toHaveBeenCalledWith({
      search_word: '',
      current_page: 1,
      page_size: 20,
      category: '',
    })
    expect(wrapper.text()).toContain('Skills管理')
    expect(wrapper.text()).toContain('Frontend Skill')
    expect(wrapper.text()).toContain('frontend-skill')
    expect(wrapper.text()).toContain('prompt')
    expect(wrapper.text()).toContain('frontend')

    await wrapper.find('input').setValue('frontend')
    const searchButton = wrapper.findAll('button').find((b) => b.text().includes('搜索'))
    await searchButton!.trigger('click')
    await flushPromises()

    expect(mocks.listAdminSkills).toHaveBeenLastCalledWith({
      search_word: 'frontend',
      current_page: 1,
      page_size: 20,
      category: '',
    })
  })
})
