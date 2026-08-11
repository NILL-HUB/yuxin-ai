import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'
import enUS from '@/i18n/messages/en-US'
import zhCN from '@/i18n/messages/zh-CN'
import type { HomeIntentData } from '@/models/home'

const readHomeModel = () =>
  readFileSync(resolve(process.cwd(), 'src/models/home.ts'), 'utf8')

const orchestrationData: HomeIntentData = {
  intent: '编程任务',
  confidence: 0.9,
  should_ask_continue: false,
  resume_question: '',
  suggested_actions: [],
  is_default: false,
  task_plan_summary: {
    execution_mode: 'multi_agent_parallel',
    reason: 'complex_multi_domain',
    task_count: 2,
    items: [
      {
        task_id: 'task-1',
        title: '研究',
        agent_pool: 'research',
        execution_order: 0,
        risk_level: 'safe',
      },
    ],
  },
  synthesis_summary: {
    final_answer: '',
    summary: 'execution_not_started',
    confidence: 0,
    visible_sources: [],
    user_warnings: [],
  },
}

describe('Home models', () => {
  it('should expose phase 6 summaries without raw agent output', () => {
    expect(orchestrationData.task_plan_summary.task_count).toBe(2)
    expect(orchestrationData.synthesis_summary.summary).toBe(
      'execution_not_started',
    )

    const source = readHomeModel()
    expect(source).toContain('task_plan_summary')
    expect(source).toContain('synthesis_summary')
    expect(source).not.toContain('raw_agent_outputs')
    expect(source).not.toContain('internal_notes')
  })

  it('should define phase 6 orchestration labels in all locales', () => {
    expect(zhCN.home.orchestration.taskPlan).toBe('任务计划')
    expect(zhCN.home.orchestration.synthesis).toBe('结果汇总')
    expect(enUS.home.orchestration.taskPlan).toBe('Task plan')
    expect(enUS.home.orchestration.synthesis).toBe('Result synthesis')
  })
})
