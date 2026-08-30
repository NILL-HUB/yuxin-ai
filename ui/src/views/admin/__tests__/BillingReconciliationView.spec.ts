import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { defineComponent, h, inject, onMounted, provide, ref } from 'vue'
import BillingReconciliationView from '@/views/admin/BillingReconciliationView.vue'

const mocks = vi.hoisted(() => ({
  listReconciliations: vi.fn(),
  getMarginSummary: vi.fn(),
  messageSuccess: vi.fn(),
  messageError: vi.fn(),
}))

vi.mock('@/services/admin-billing-reconciliation', () => ({
  listReconciliations: mocks.listReconciliations,
  getMarginSummary: mocks.getMarginSummary,
}))

vi.mock('@arco-design/web-vue', () => ({
  Message: {
    success: mocks.messageSuccess,
    error: mocks.messageError,
  },
}))

// Table stub that collects cell slots from a-table-column via provide/inject
const tableStub = defineComponent({
  props: ['data', 'columns', 'loading', 'pagination', 'bordered', 'rowKey', 'size'],
  setup(props, { slots }) {
    const cellSlots = ref<Array<(props: { record: Record<string, unknown> }) => unknown>>([])
    provide('cellSlots', cellSlots)
    return () => h('div', { class: 'a-table' }, [
      h('div', { style: 'display:none' }, slots.columns?.()),
      ...(props.data || []).map((row: Record<string, unknown>) => {
        const rowKey = props.rowKey as string | undefined
        const rowId = rowKey && row[rowKey] != null
          ? String(row[rowKey])
          : String(row.id ?? row.task_id ?? row.model_name ?? '')
        return h(
          'div',
          { class: 'table-row', 'data-id': rowId },
          cellSlots.value.map((cellSlot) =>
            h(
              'div',
              { class: 'table-cell' },
              cellSlot({ record: row }) as unknown as import('vue').VNode,
            ),
          ),
        )
      }),
    ])
  },
})

const tableColumnStub = defineComponent({
  props: ['title', 'width', 'dataIndex', 'align'],
  setup(props, { slots }) {
    const cellSlots = inject<
      import('vue').Ref<Array<(props: { record: Record<string, unknown> }) => unknown>>
    >('cellSlots', ref([]))
    onMounted(() => {
      if (slots.cell) {
        cellSlots.value.push(slots.cell as (props: { record: Record<string, unknown> }) => unknown)
      } else {
        cellSlots.value.push(({ record }) =>
          h(
            'span',
            { class: 'table-cell-text' },
            String((record as Record<string, unknown>)[props.dataIndex as string] ?? ''),
          ),
        )
      }
    })
    return () => null
  },
})

const tagStub = {
  props: ['color', 'size'],
  template: '<span class="arco-tag" :data-color="color"><slot /></span>',
}

const marginSummary = {
  list: [
    { model_name: 'gpt-4o', calls: 2, actual: 200, cost: 80, margin: 120 },
    { model_name: 'billing-losing', calls: 3, actual: 90, cost: 110, margin: -20 },
  ],
  total_margin: 100,
  total_actual: 290,
  overall: { actual_credits: 290, cost_credits: 190, margin_credits: 100 },
  by_tier: [
    { tier: 'peak', calls: 2, actual_credits: 150, cost_credits: 80, margin_credits: 70 },
    { tier: '常规', calls: 3, actual_credits: 140, cost_credits: 110, margin_credits: 30 },
  ],
  cached_input_tokens_total: 700,
}

const reconciliations = [
  {
    id: 'r1',
    task_id: 'task-abc123',
    account_id: 'acc-1',
    estimated_credits: 8,
    actual_credits: 7,
    cost_credits: 5,
    diff_credits: -1,
    status: 'settled',
    alert_flags: ['ratio_deviation'],
    created_at: 1750000000,
  },
  {
    id: 'r2',
    task_id: 'task-def456',
    account_id: 'acc-2',
    estimated_credits: 100,
    actual_credits: 200,
    cost_credits: 250,
    diff_credits: 100,
    status: 'settled',
    alert_flags: ['negative_margin'],
    created_at: 1750000001,
  },
]

const renderView = async () => {
  mocks.getMarginSummary.mockResolvedValue(marginSummary)
  mocks.listReconciliations.mockResolvedValue({
    list: reconciliations,
    paginator: { total_record: 2, total_page: 1, current_page: 1, page_size: 20 },
  })
  const wrapper = mount(BillingReconciliationView, {
    global: {
      stubs: {
        'a-table': tableStub,
        'a-table-column': tableColumnStub,
        'a-tag': tagStub,
      },
    },
  })
  await flushPromises()
  return wrapper
}

describe('BillingReconciliationView', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('loads margin summary and reconciliation list in parallel and renders stats', async () => {
    const wrapper = await renderView()

    expect(mocks.getMarginSummary).toHaveBeenCalledTimes(1)
    expect(mocks.listReconciliations).toHaveBeenCalledWith({ current_page: 1, page_size: 20 })

    expect(wrapper.text()).toContain('对账与毛利看板')
    const statValues = wrapper.findAll('strong').map((node) => node.text())
    expect(statValues).toContain('290') // 实际算力（售价）
    expect(statValues).toContain('190') // 成本算力 = 80 + 110
    expect(statValues).toContain('100') // 总毛利
    expect(statValues).toContain('2') // 告警行数

    expect(wrapper.text()).toContain('gpt-4o')
    expect(wrapper.text()).toContain('billing-losing')
    expect(wrapper.text()).toContain('task-abc123')
  })

  it('renders negative margin as red tag and positive margin as green tag', async () => {
    const wrapper = await renderView()

    const redTags = wrapper.findAll('[data-color="red"]')
    const greenTags = wrapper.findAll('[data-color="green"]')
    expect(redTags.some((node) => node.text() === '-20')).toBe(true)
    expect(greenTags.some((node) => node.text() === '120')).toBe(true)
  })

  it('renders alert flag tags with distinct colors and labels', async () => {
    const wrapper = await renderView()

    const orangeTags = wrapper.findAll('[data-color="orange"]')
    expect(orangeTags.some((node) => node.text() === '偏差超限')).toBe(true)

    const redTags = wrapper.findAll('[data-color="red"]')
    expect(redTags.some((node) => node.text() === '亏本')).toBe(true)
  })

  it('shows empty states when no margin or reconciliation data', async () => {
    mocks.getMarginSummary.mockResolvedValue({
      list: [],
      total_margin: 0,
      total_actual: 0,
      overall: { actual_credits: 0, cost_credits: 0, margin_credits: 0 },
      by_tier: [],
      cached_input_tokens_total: 0,
    })
    mocks.listReconciliations.mockResolvedValue({
      list: [],
      paginator: { total_record: 0, total_page: 0, current_page: 1, page_size: 20 },
    })
    const wrapper = mount(BillingReconciliationView, {
      global: {
        stubs: {
          'a-table': tableStub,
          'a-table-column': tableColumnStub,
          'a-tag': tagStub,
        },
      },
    })
    await flushPromises()

    expect(wrapper.text()).toContain('暂无毛利数据')
    expect(wrapper.text()).toContain('暂无对账记录')

    const statValues = wrapper.findAll('strong').map((node) => node.text())
    expect(statValues.every((value) => value === '0')).toBe(true)
  })

  it('renders margin summary grouped by tier with cache totals', async () => {
    const wrapper = await renderView()

    expect(wrapper.text()).toContain('按档位汇总')
    expect(wrapper.text()).toContain('peak')
    expect(wrapper.text()).toContain('常规')
    expect(wrapper.text()).toContain('缓存命中输入 Token 合计')
    expect(wrapper.text()).toContain('700')

    const tierRows = wrapper.findAll('.table-row')
    expect(tierRows.length).toBeGreaterThan(0)
    const tierRow = tierRows.find(
      (node) => node.attributes('data-id') === 'peak',
    )
    expect(tierRow).toBeTruthy()
    expect(tierRow?.text()).toContain('70')
  })

  it('renders empty tier table when by_tier is empty', async () => {
    mocks.getMarginSummary.mockResolvedValue({
      list: [],
      total_margin: 0,
      total_actual: 0,
      overall: { actual_credits: 0, cost_credits: 0, margin_credits: 0 },
      by_tier: [],
      cached_input_tokens_total: 0,
    })
    mocks.listReconciliations.mockResolvedValue({
      list: [],
      paginator: { total_record: 0, total_page: 0, current_page: 1, page_size: 20 },
    })
    const wrapper = mount(BillingReconciliationView, {
      global: {
        stubs: {
          'a-table': tableStub,
          'a-table-column': tableColumnStub,
          'a-tag': tagStub,
        },
      },
    })
    await flushPromises()

    expect(wrapper.text()).toContain('按档位汇总')
    expect(wrapper.text()).toContain('缓存命中输入 Token 合计：0')
    const peakRows = wrapper.findAll('.table-row').filter(
      (node) => node.attributes('data-id') === 'peak',
    )
    expect(peakRows).toHaveLength(0)
  })
})