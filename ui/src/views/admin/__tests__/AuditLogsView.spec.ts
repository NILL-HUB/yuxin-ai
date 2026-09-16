import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import AuditLogsView from '@/views/admin/AuditLogsView.vue'

const mocks = vi.hoisted(() => ({
  listAuditLogs: vi.fn(),
  getAuditLogOverview: vi.fn(),
  messageError: vi.fn(),
}))

vi.mock('@/services/admin-audit-logs', () => ({
  listAuditLogs: mocks.listAuditLogs,
  getAuditLogOverview: mocks.getAuditLogOverview,
}))

vi.mock('@arco-design/web-vue', () => ({
  Message: {
    error: mocks.messageError,
  },
}))

const tValues: Record<string, string> = {
  'admin.auditLogs.title': 'Audit logs',
  'admin.auditLogs.description': 'Review admin actions',
  'admin.auditLogs.timeRange': 'Time range',
  'admin.auditLogs.range7d': 'Last 7 days',
  'admin.auditLogs.range30d': 'Last 30 days',
  'admin.auditLogs.range90d': 'Last 90 days',
  'admin.auditLogs.range180d': 'Last 180 days',
  'admin.auditLogs.rangeAll': 'All time',
  'admin.auditLogs.refresh': 'Refresh',
  'admin.auditLogs.totalCount': 'Total audits',
  'admin.auditLogs.totalCountHint': 'Total in range',
  'admin.auditLogs.activeAdmins': 'Active admins',
  'admin.auditLogs.activeAdminsHint': 'Admins active in range',
  'admin.auditLogs.trendTotal': 'Trend total',
  'admin.auditLogs.trendTotalHint': 'Sum over days',
  'admin.auditLogs.trendPeak': 'Peak / day',
  'admin.auditLogs.trendPeakHint': 'Largest day',
  'admin.auditLogs.trendTitle': 'Daily audit trend',
  'admin.auditLogs.trendDescription': 'Entries per day',
  'admin.auditLogs.actionDistribution': 'Action distribution',
  'admin.auditLogs.actionDistributionDesc': 'By action',
  'admin.auditLogs.resourceDistribution': 'Resource distribution',
  'admin.auditLogs.resourceDistributionDesc': 'Top resources',
  'admin.auditLogs.topAdmins': 'Top admins',
  'admin.auditLogs.topAdminsDesc': 'Most active admins',
  'admin.auditLogs.listTitle': 'Audit details',
  'admin.auditLogs.listDescription': 'Detailed records',
  'admin.auditLogs.allActions': 'All actions',
  'admin.auditLogs.actionCreate': 'Create',
  'admin.auditLogs.actionUpdate': 'Update',
  'admin.auditLogs.actionDisable': 'Disable',
  'admin.auditLogs.actionDelete': 'Delete',
  'admin.auditLogs.actionTypePlaceholder': 'Action type',
  'admin.auditLogs.resourceTypePlaceholder': 'Resource type',
  'admin.auditLogs.startTimePlaceholder': 'Start time',
  'admin.auditLogs.endTimePlaceholder': 'End time',
  'admin.auditLogs.search': 'Search',
  'admin.auditLogs.time': 'Time',
  'admin.auditLogs.admin': 'Admin',
  'admin.auditLogs.action': 'Action',
  'admin.auditLogs.resourceType': 'Resource Type',
  'admin.auditLogs.resource': 'Resource',
  'admin.auditLogs.resourceId': 'Resource ID',
  'admin.auditLogs.resourceNameLabel': 'Resource Name:',
  'admin.auditLogs.detail': 'Detail',
  'admin.auditLogs.loadFailed': 'Load failed',
  'admin.auditLogs.view': 'View',
  'admin.auditLogs.loading': 'Loading...',
  'admin.auditLogs.noData': 'No data',
  'admin.auditLogs.detailTitle': 'Audit Detail',
  'admin.auditLogs.actionLabel': 'Action:',
  'admin.auditLogs.resourceTypeLabel': 'Resource Type:',
  'admin.auditLogs.resourceIdLabel': 'Resource ID:',
  'admin.auditLogs.beforeChange': 'Before Change',
  'admin.auditLogs.afterChange': 'After Change',
  'admin.auditLogs.unknownResource': 'Unknown resource',
  'admin.auditLogs.ipLabel': 'IP:',
  'admin.auditLogs.userAgentLabel': 'User-Agent:',
  'admin.auditLogs.resourceWorkflow': 'Workflow',
  'admin.auditLogs.resourceAdminUser': 'Admin User',
  'admin.auditLogs.resourceApp': 'App',
  'admin.auditLogs.resourceRole': 'Role',
}

vi.mock('vue-i18n', () => ({
  useI18n: () => ({
    t: (key: string, params?: Record<string, number>) => {
      const template = tValues[key] ?? key
      if (params) {
        return template.replace(/\{(\w+)\}/g, (_, name: string) => String(params[name]))
      }
      return template
    },
  }),
}))

const buttonStub = {
  props: ['loading', 'size', 'type'],
  emits: ['click'],
  template: '<button type="button" :disabled="loading" @click="$emit(\'click\')"><slot /></button>',
}

const tagStub = {
  props: ['color', 'size'],
  template: '<span class="a-tag" :data-color="color"><slot /></span>',
}

const paginationStub = {
  props: ['total', 'current', 'pageSize', 'showTotal', 'showPageSize'],
  emits: ['change', 'page-size-change'],
  template: '<div class="a-pagination"></div>',
}

const modalStub = {
  props: ['visible', 'title', 'width', 'footer'],
  emits: ['cancel'],
  template:
    '<div v-if="visible" class="a-modal"><h3 class="modal-title">{{ title }}</h3><slot /></div>',
}

const tooltipStub = {
  props: ['content', 'position', 'mini'],
  inheritAttrs: false,
  template: '<span class="a-tooltip" :data-content="content"><slot /></span>',
}

const inputStub = {
  props: ['modelValue', 'placeholder'],
  emits: ['update:modelValue'],
  template: '<input :value="modelValue" :placeholder="placeholder" />',
}

const selectStub = {
  props: ['modelValue', 'options', 'placeholder'],
  emits: ['update:modelValue'],
  template:
    '<select :value="modelValue"><option v-for="option in (options || [])" :key="option.value" :value="option.value">{{ option.label }}</option></select>',
}

const overviewFixture = {
  total: 250,
  by_action: [
    { name: 'create', count: 120 },
    { name: 'update', count: 80 },
    { name: 'delete', count: 50 },
  ],
  by_resource_type: [
    { name: 'workflow', count: 100 },
    { name: 'app', count: 60 },
    { name: 'role', count: 40 },
  ],
  trend: [
    { timestamp: 1765843200, count: 10 },
    { timestamp: 1765929600, count: 20 },
  ],
  top_admins: [
    { name: 'admin@example.com', count: 90 },
    { name: 'ops@example.com', count: 60 },
  ],
}

const logFixture = {
  id: 'audit-1',
  admin_user_name: 'root',
  action: 'create',
  resource_type: 'workflow',
  resource_id: 'workflow-12345678',
  resource_name: 'Onboarding Flow',
  ip: '127.0.0.1',
  user_agent: 'Mozilla/5.0',
  before_data: { name: 'old' },
  after_data: { name: 'new' },
  created_at: 1765843200,
}

const renderView = async () => {
  mocks.listAuditLogs.mockResolvedValue({
    data: {
      list: [{ ...logFixture }],
      paginator: { total_record: 1, total_page: 1, current_page: 1, page_size: 20 },
    },
  })
  mocks.getAuditLogOverview.mockResolvedValue({ data: { ...overviewFixture } })

  const wrapper = mount(AuditLogsView, {
    global: {
      stubs: {
        'a-input': inputStub,
        'a-select': selectStub,
        'a-button': buttonStub,
        'a-tag': tagStub,
        'a-pagination': paginationStub,
        'a-modal': modalStub,
        'a-tooltip': tooltipStub,
      },
    },
  })
  await flushPromises()
  return wrapper
}

describe('AuditLogsView', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-01-15T00:00:00Z'))
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('loads overview and list on mount, renders KPIs, trend and distributions', async () => {
    const wrapper = await renderView()

    expect(mocks.getAuditLogOverview).toHaveBeenCalledTimes(1)
    expect(mocks.listAuditLogs).toHaveBeenCalledTimes(1)
    expect(mocks.getAuditLogOverview).toHaveBeenCalledWith({
      action: undefined,
      resource_type: undefined,
      start_time: 1765843200,
      end_time: 1768435200,
    })
    expect(mocks.listAuditLogs).toHaveBeenCalledWith({
      action: undefined,
      resource_type: undefined,
      start_time: 1765843200,
      end_time: 1768435200,
      current_page: 1,
      page_size: 20,
    })

    expect(wrapper.text()).toContain('Audit logs')
    expect(wrapper.text()).toContain('Total audits')
    expect(wrapper.text()).toContain('250')
    expect(wrapper.text()).toContain('Active admins')
    expect(wrapper.text()).toContain('Trend total')
    expect(wrapper.text()).toContain('30')
    expect(wrapper.text()).toContain('Peak / day')
    expect(wrapper.text()).toContain('20')
    expect(wrapper.text()).toContain('Daily audit trend')
    expect(wrapper.text()).toContain('Action distribution')
    expect(wrapper.text()).toContain('Create')
    expect(wrapper.text()).toContain('Resource distribution')
    expect(wrapper.text()).toContain('Workflow')
    expect(wrapper.text()).toContain('Top admins')
    expect(wrapper.text()).toContain('admin@example.com')

    expect(
      wrapper.find('[aria-label="trend-section"] svg rect[fill="#0ea5e9"]').exists(),
    ).toBe(true)
    expect(wrapper.find('[aria-label="overview-section"]').exists()).toBe(true)
    expect(wrapper.find('[aria-label="trend-section"]').exists()).toBe(true)
    expect(wrapper.find('[aria-label="distribution-section"]').exists()).toBe(true)
    expect(wrapper.find('[aria-label="list-section"]').exists()).toBe(true)
  })

  it('refetches overview and list with new range params when the range selector changes', async () => {
    const wrapper = await renderView()

    mocks.getAuditLogOverview.mockClear()
    mocks.listAuditLogs.mockClear()

    const buttons = wrapper.findAll('button')
    const rangeButtons = buttons.filter((button) => button.attributes('aria-pressed') !== undefined)
    const sevenDayButton = rangeButtons.find((button) => button.text().includes('Last 7 days'))
    expect(sevenDayButton).toBeDefined()

    await sevenDayButton!.trigger('click')
    await flushPromises()

    expect(mocks.getAuditLogOverview).toHaveBeenCalledWith({
      action: undefined,
      resource_type: undefined,
      start_time: 1767830400,
      end_time: 1768435200,
    })
    expect(mocks.listAuditLogs).toHaveBeenCalledWith({
      action: undefined,
      resource_type: undefined,
      start_time: 1767830400,
      end_time: 1768435200,
      current_page: 1,
      page_size: 20,
    })

    mocks.getAuditLogOverview.mockClear()
    mocks.listAuditLogs.mockClear()

    const allTimeButton = rangeButtons.find((button) => button.text().includes('All time'))
    await allTimeButton!.trigger('click')
    await flushPromises()

    expect(mocks.getAuditLogOverview).toHaveBeenCalledWith({
      action: undefined,
      resource_type: undefined,
      start_time: undefined,
      end_time: undefined,
    })
    expect(mocks.listAuditLogs).toHaveBeenCalledWith({
      action: undefined,
      resource_type: undefined,
      start_time: undefined,
      end_time: undefined,
      current_page: 1,
      page_size: 20,
    })
  })

  it('renders the audit log table with action badge, resource name and truncated resource id', async () => {
    const wrapper = await renderView()

    expect(wrapper.text()).toContain('Audit details')
    expect(wrapper.text()).toContain('root')
    expect(wrapper.text()).toContain('Onboarding Flow')
    expect(wrapper.text()).toContain('workflow...')
    expect(wrapper.find('.a-tooltip').attributes('data-content')).toBe('workflow-12345678')
    expect(wrapper.text()).toContain('View')
    const tags = wrapper.findAll('.a-tag')
    expect(tags.some((tag) => tag.attributes('data-color') === 'green')).toBe(true)
  })

  it('falls back to truncated resource id when resource name is missing', async () => {
    mocks.listAuditLogs.mockResolvedValue({
      data: {
        list: [{ ...logFixture, resource_name: undefined }],
        paginator: { total_record: 1, total_page: 1, current_page: 1, page_size: 20 },
      },
    })
    mocks.getAuditLogOverview.mockResolvedValue({ data: { ...overviewFixture } })

    const wrapper = mount(AuditLogsView, {
      global: {
        stubs: {
          'a-input': inputStub,
          'a-select': selectStub,
          'a-button': buttonStub,
          'a-tag': tagStub,
          'a-pagination': paginationStub,
          'a-modal': modalStub,
          'a-tooltip': tooltipStub,
        },
      },
    })
    await flushPromises()

    expect(wrapper.text()).toContain('workflow...')
    expect(wrapper.find('.a-tooltip').attributes('data-content')).toBe('workflow-12345678')
  })

  it('opens the detail modal with before/after change JSON', async () => {
    const wrapper = await renderView()

    const viewButton = wrapper.findAll('button').find((button) => button.text() === 'View')
    expect(viewButton).toBeDefined()
    await viewButton!.trigger('click')
    await flushPromises()

    const modal = wrapper.find('.a-modal')
    expect(modal.exists()).toBe(true)
    expect(modal.text()).toContain('Audit Detail')
    expect(modal.text()).toContain('Resource Name:')
    expect(modal.text()).toContain('Onboarding Flow')
    expect(modal.text()).toContain('Mozilla/5.0')
    expect(modal.text()).toContain('Before Change')
    expect(modal.text()).toContain('After Change')
    expect(modal.text()).toContain('"name": "old"')
    expect(modal.text()).toContain('"name": "new"')
  })

  it('shows error message when loading fails', async () => {
    mocks.listAuditLogs.mockRejectedValue(new Error('boom'))
    mocks.getAuditLogOverview.mockRejectedValue(new Error('boom'))

    mount(AuditLogsView, {
      global: {
        stubs: {
          'a-button': buttonStub,
        },
      },
    })
    await flushPromises()

    expect(mocks.messageError).toHaveBeenCalled()
  })
})
