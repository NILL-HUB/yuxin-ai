import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import BillingUsageIndicator from '../BillingUsageIndicator.vue'
import type { BillingUsageEvent } from '@/models/billing-metering'

vi.mock('vue-i18n', () => ({
  useI18n: () => ({
    t: (key: string) =>
      ({
        'billing.usage.occurred': 'Consumed',
        'billing.usage.cancelled': 'Stopped',
        'billing.usage.unit': 'credits',
      })[key] ?? key,
  }),
}))

const readSource = () =>
  readFileSync(
    resolve(process.cwd(), 'src/components/BillingUsageIndicator.vue'),
    'utf8',
  )

const events: BillingUsageEvent[] = [
  {
    event: 'billing_started',
    source_type: 'summary',
    source_name: 'billing',
    delta_credits: 0,
    total_credits: 0,
    reason: 'billing_started',
  },
  {
    event: 'billing_delta',
    source_type: 'model',
    source_name: 'deepseek-chat',
    delta_credits: 3,
    total_credits: 3,
    reason: 'tokens',
  },
]

describe('BillingUsageIndicator.vue', () => {
  it('should render current occurred credits only', () => {
    const wrapper = mount(BillingUsageIndicator, {
      props: { events },
    })

    expect(wrapper.text()).toContain('Consumed')
    expect(wrapper.text()).toContain('3')
    expect(wrapper.text()).toContain('credits')
    expect(wrapper.text()).not.toContain('预估')
    expect(wrapper.text()).not.toContain('key-1')
    expect(wrapper.text()).not.toContain('deepseek-chat')
    expect(wrapper.text()).not.toContain('internal_cost_breakdown')
  })

  it('should use i18n keys instead of hardcoded display text', () => {
    const source = readSource()

    expect(source).toContain("t('billing.usage.occurred')")
    expect(source).toContain("t('billing.usage.cancelled')")
    expect(source).toContain("t('billing.usage.unit')")
    expect(source).not.toContain('已消耗')
    expect(source).not.toContain('已停止')
  })

  it('should render cancelled status with current cost', () => {
    const wrapper = mount(BillingUsageIndicator, {
      props: {
        events: [
          ...events,
          {
            event: 'billing_cancelled',
            source_type: 'summary',
            source_name: 'billing',
            delta_credits: 0,
            total_credits: 3,
            reason: 'user_stop',
          },
        ],
      },
    })

    expect(wrapper.text()).toContain('Stopped')
    expect(wrapper.text()).toContain('3')
  })
})
