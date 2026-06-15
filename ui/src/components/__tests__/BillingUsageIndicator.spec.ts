import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import BillingUsageIndicator from '../BillingUsageIndicator.vue'
import type { BillingUsageEvent } from '@/models/billing-metering'

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

    expect(wrapper.text()).toContain('已消耗')
    expect(wrapper.text()).toContain('3')
    expect(wrapper.text()).not.toContain('预估')
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

    expect(wrapper.text()).toContain('已停止')
    expect(wrapper.text()).toContain('3')
  })
})
