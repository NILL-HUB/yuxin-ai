import { flushPromises, shallowMount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'

vi.mock('@/services/schedule-task', () => ({
  createScheduleTask: vi.fn().mockResolvedValue({ data: {} }),
  updateScheduleTask: vi.fn().mockResolvedValue({ data: {} }),
  humanizeScheduleCron: vi.fn().mockResolvedValue({ data: { cron_humanized: '每天 14:00' } }),
  parseScheduleIntent: vi.fn().mockResolvedValue({ data: {} }),
  rejectScheduleSuggestion: vi.fn(),
}))

vi.mock('vue-router', () => ({
  useRoute: () => ({ path: '/', meta: {} }),
}))

vi.mock('@arco-design/web-vue', () => ({
  Message: {
    error: vi.fn(),
    success: vi.fn(),
    warning: vi.fn(),
  },
}))

import { nextTick } from 'vue'

import CreateScheduleWizard from '../CreateScheduleWizard.vue'

const intervalTask = {
  id: 'task-interval-1',
  name: '间隔测试',
  prompt: '测试',
  trigger_type: 'interval' as const,
  cron_expression: '0 0 0 * * *',
  cron_humanized: '',
  interval_config: { unit: 'day' as const, every: 2, hours: 14 },
  enabled: true,
  status: 'active',
  description: '',
  run_count: 0,
  last_run_at: null,
  last_run_status: null,
  last_result: null,
  next_run_at: null,
  created_at: 0,
  updated_at: 0,
}

const cronTask = {
  ...intervalTask,
  id: 'task-cron-1',
  trigger_type: 'cron' as const,
  cron_expression: '0 30 14 * * *',
  cron_humanized: '每天 14:30',
  interval_config: {},
}

// 每周一和周五 17:00（多选周几）
const multiWeekdayTask = {
  ...intervalTask,
  id: 'task-multi-1',
  trigger_type: 'cron' as const,
  cron_expression: '0 0 17 * * 1,5',
  cron_humanized: '每周一、周五 17:00:00',
  interval_config: {},
}

describe('CreateScheduleWizard 日历与间隔同步', () => {
  it('日历区渲染全部周期类型（含按分钟/按小时）', async () => {
    const wrapper = shallowMount(CreateScheduleWizard, {
      props: { visible: false, task: cronTask },
    })
    await nextTick()
    await wrapper.setProps({ visible: true })
    await flushPromises()

    const text = wrapper.text()
    expect(text).toContain('每天')
    expect(text).toContain('每周')
    expect(text).toContain('每月')
    expect(text).toContain('按分钟')
    expect(text).toContain('按小时')
    expect(text).toContain('当前设置')
  })

  it('编辑 interval 任务时，日历摘要显示间隔配置', async () => {
    const wrapper = shallowMount(CreateScheduleWizard, {
      props: { visible: false, task: intervalTask },
    })
    await nextTick()
    await wrapper.setProps({ visible: true })
    await flushPromises()

    expect(wrapper.text()).toContain('每隔 2 天 14:00')
  })

  it('编辑 cron 任务时，日历摘要显示 cron 描述', async () => {
    const wrapper = shallowMount(CreateScheduleWizard, {
      props: { visible: false, task: cronTask },
    })
    await nextTick()
    await wrapper.setProps({ visible: true })
    await flushPromises()

    expect(wrapper.text()).toContain('每天 14:30')
  })

  it('编辑每周一和周五任务时，日历摘要显示多周几描述', async () => {
    const wrapper = shallowMount(CreateScheduleWizard, {
      props: { visible: false, task: multiWeekdayTask },
    })
    await nextTick()
    await wrapper.setProps({ visible: true })
    await flushPromises()

    expect(wrapper.text()).toContain('每周一、周五 17:00:00')
  })
})
