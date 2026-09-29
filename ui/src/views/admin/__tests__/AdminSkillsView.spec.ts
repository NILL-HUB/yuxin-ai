import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import AdminSkillsView from '@/views/admin/AdminSkillsView.vue'
import {
  SKILL_SYNC_STATUSES,
  resolveSkillSyncDescriptor,
  resolveSkillSyncNotice,
} from '@/utils/admin-skill-sync'

const mocks = vi.hoisted(() => ({
  listAdminSkills: vi.fn(),
  messageSuccess: vi.fn(),
  messageWarning: vi.fn(),
  messageInfo: vi.fn(),
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
      success: mocks.messageSuccess,
      warning: mocks.messageWarning,
      info: mocks.messageInfo,
      error: mocks.messageError,
    },
  }
})

vi.mock('vue-i18n', () => ({
  useI18n: () => ({
    locale: { value: 'zh-CN' },
    t: (key: string, params?: { count?: number; reason?: string }) =>
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
          'admin.skillsAdmin.all': '全部',
          'admin.skillsAdmin.detailTitle': '技能详情',
          'admin.skillsAdmin.executor': '执行器',
          'admin.skillsAdmin.toolCountLabel': '工具数量',
          'admin.skillsAdmin.toolsTitle': '包含工具',
          'admin.skillsAdmin.toolCountBadge': `${params?.count ?? 0} 个工具`,
          'admin.skillsAdmin.promptOnly': '仅提示词',
          'admin.skillsAdmin.noBody': '暂无内容',
          'admin.skillsAdmin.executorTypes.scf': '可执行',
          'admin.skillsAdmin.executorTypes.tool': '工具',
          'admin.skillsAdmin.executorTypes.prompt': '仅提示词',
          'admin.skillsAdmin.syncStatus': '同步状态',
          'admin.skillsAdmin.syncReady': '已同步',
          'admin.skillsAdmin.syncPending': '待同步',
          'admin.skillsAdmin.syncSkipped': '已跳过',
          'admin.skillsAdmin.syncNotConfigured': '未配置',
          'admin.skillsAdmin.syncUnknown': '未知状态',
          'admin.skillsAdmin.syncFailed': '同步失败',
          'admin.skillsAdmin.syncResultReason': `同步说明：${params?.reason ?? ''}`,
          'admin.skillsAdmin.syncNoReason': '未提供原因',
          'admin.skillsAdmin.syncSucceeded': '同步完成',
          'admin.skillsAdmin.syncSkippedNotice': '该技能无需同步到远端',
          'admin.skillsAdmin.syncNotConfiguredNotice': `远端 SCF 未配置，已跳过同步：${params?.reason ?? ''}`,
          'admin.skillsAdmin.syncFailedNotice': `同步失败：${params?.reason ?? ''}`,
          'admin.skillsAdmin.syncUnknownNotice': '已提交同步，但未返回明确结果',
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
      page_size: 100,
      category: '',
    })
    expect(wrapper.text()).toContain('Skills管理')
    expect(wrapper.text()).toContain('Frontend Skill')
    expect(wrapper.text()).toContain('frontend-skill')
    expect(wrapper.text()).toContain('仅提示词')
    expect(wrapper.text()).toContain('frontend')

    await wrapper.find('input').setValue('frontend')
    const searchButton = wrapper.findAll('button').find((b) => b.text().includes('搜索'))
    await searchButton!.trigger('click')
    await flushPromises()

    expect(mocks.listAdminSkills).toHaveBeenLastCalledWith({
      search_word: 'frontend',
      current_page: 1,
      page_size: 100,
      category: '',
    })
  })
})

/**
 * 结构性守卫：后端 sync_status 的**每一个**合法取值都必须映射到有语义的文案。
 *
 * 历史缺陷：`skipped` 漏映射 → 前端显示裸英文码；后端把"未配置"写成 `pending`
 * → 前端显示"同步中"且永无终态。下面的用例专门锁死这两类回归。
 */
describe('admin skill sync status mapping', () => {
  it('maps every backend status to a semantic label (never a raw code)', () => {
    for (const status of SKILL_SYNC_STATUSES) {
      const descriptor = resolveSkillSyncDescriptor(status)
      expect(descriptor.key).not.toBe('unknown')
      expect(descriptor.labelKey).toMatch(/^admin\.skillsAdmin\./)
      expect(descriptor.labelKey).not.toBe('admin.skillsAdmin.syncUnknown')
    }
  })

  it('does not collapse two distinct statuses onto the same semantic key', () => {
    const keys = SKILL_SYNC_STATUSES.map((status) => resolveSkillSyncDescriptor(status).key)
    expect(new Set(keys).size).toBe(keys.length)
  })

  it('maps not_configured to a dedicated, non-green descriptor', () => {
    const descriptor = resolveSkillSyncDescriptor('not_configured')
    expect(descriptor.key).toBe('not_configured')
    expect(descriptor.labelKey).toBe('admin.skillsAdmin.syncNotConfigured')
    expect(descriptor.color).not.toBe('green')
  })

  it('renders unknown statuses as a generic label, keeping the raw value for diagnostics', () => {
    const descriptor = resolveSkillSyncDescriptor('weird_value')
    expect(descriptor.key).toBe('unknown')
    expect(descriptor.labelKey).toBe('admin.skillsAdmin.syncUnknown')
    expect(descriptor.raw).toBe('weird_value')
  })

  it('never reports a non-completed sync as success', () => {
    expect(resolveSkillSyncNotice('synced').level).toBe('success')
    expect(resolveSkillSyncNotice('failed').level).toBe('error')
    expect(resolveSkillSyncNotice('not_configured').level).toBe('warning')
    expect(resolveSkillSyncNotice('skipped').level).toBe('info')
    expect(resolveSkillSyncNotice('').level).toBe('info')
  })
})
