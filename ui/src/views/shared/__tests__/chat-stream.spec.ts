import { describe, expect, it } from 'vitest'
import { QueueEvent } from '@/config'
import {
  applyChatStreamEvent,
  mergeChatHistoryMessages,
  withChatRenderId,
  type StreamEventResponse,
  type StreamMessage,
  type StreamState,
} from '@/views/shared/chat-stream'

const createMessage = (): StreamMessage => ({
  id: '',
  conversation_id: '',
  answer: '',
  answer_parts: [],
  artifacts: [],
  latency: 0,
  total_token_count: 0,
  agent_thoughts: [],
})

const createState = (): StreamState => ({
  position: 0,
  message_id: '',
  task_id: '',
  conversation_id: '',
  billingEvents: [],
})

describe('chat-stream', () => {
  it('appends agent message content and initializes ids', () => {
    const message = createMessage()
    const state = createState()
    const event: StreamEventResponse = {
      event: QueueEvent.agentMessage,
      data: {
        id: 'event-1',
        event: QueueEvent.agentMessage,
        thought: '你好',
        message_id: 'message-1',
        task_id: 'task-1',
        conversation_id: 'conversation-1',
        latency: 1.2,
        total_token_count: 21,
      },
    }

    const result = applyChatStreamEvent(message, event, state)

    expect(result.didUpdate).toBe(true)
    expect(result.state.position).toBe(1)
    expect(result.state.message_id).toBe('message-1')
    expect(result.state.task_id).toBe('task-1')
    expect(result.state.conversation_id).toBe('conversation-1')
    expect(message.id).toBe('message-1')
    expect(message.conversation_id).toBe('conversation-1')
    expect(message.answer).toBe('你好')
    expect(message.latency).toBe(1.2)
    expect(message.total_token_count).toBe(21)
    expect(message.agent_thoughts).toHaveLength(1)
  })

  it('prefers aggregate metrics for message-level latency and token count', () => {
    const message = createMessage()

    applyChatStreamEvent(
      message,
      {
        event: QueueEvent.deepComplete,
        data: {
          id: 'deep-complete-1',
          event: QueueEvent.deepComplete,
          thought: '整理执行结果',
          latency: 20,
          total_token_count: 120,
          aggregate_latency: 25,
          aggregate_total_token_count: 150,
        },
      },
      createState(),
    )

    expect(message.agent_thoughts).toHaveLength(1)
    expect(message.agent_thoughts[0].latency).toBe(20)
    expect(message.latency).toBe(25)
    expect(message.total_token_count).toBe(150)
  })

  it('concatenates thought chunks for same event id', () => {
    const message = createMessage()
    let state = createState()

    const firstChunk: StreamEventResponse = {
      event: QueueEvent.agentMessage,
      data: {
        id: 'event-1',
        event: QueueEvent.agentMessage,
        thought: 'Hello',
      },
    }
    const secondChunk: StreamEventResponse = {
      event: QueueEvent.agentMessage,
      data: {
        id: 'event-1',
        event: QueueEvent.agentMessage,
        thought: ' World',
      },
    }

    state = applyChatStreamEvent(message, firstChunk, state).state
    const secondResult = applyChatStreamEvent(message, secondChunk, state)

    expect(secondResult.state.position).toBe(1)
    expect(message.answer).toBe('Hello World')
    expect(message.agent_thoughts).toHaveLength(1)
    expect(message.agent_thoughts[0].thought).toBe('Hello World')
  })

  it('keeps deep thinking chunks separate from agent message chunks', () => {
    const message = createMessage()
    let state = createState()

    const deepThinkingChunk: StreamEventResponse = {
      event: QueueEvent.deepThinking,
      data: {
        id: 'deep-1',
        event: QueueEvent.deepThinking,
        thought: '先拆解任务',
      },
    }
    const deepThinkingChunk2: StreamEventResponse = {
      event: QueueEvent.deepThinking,
      data: {
        id: 'deep-1',
        event: QueueEvent.deepThinking,
        thought: '，再执行',
      },
    }

    state = applyChatStreamEvent(message, deepThinkingChunk, state).state
    const secondResult = applyChatStreamEvent(message, deepThinkingChunk2, state)

    expect(secondResult.state.position).toBe(1)
    expect(message.answer).toBe('')
    expect(message.agent_thoughts).toHaveLength(1)
    expect(message.agent_thoughts[0].event).toBe(QueueEvent.deepThinking)
    expect(message.agent_thoughts[0].thought).toBe('先拆解任务，再执行')
  })

  it('upserts deep step events by id instead of appending duplicate rows', () => {
    const message = createMessage()
    let state = createState()

    const firstStep: StreamEventResponse = {
      event: QueueEvent.deepStep,
      data: {
        id: 'step-1',
        event: QueueEvent.deepStep,
        thought: '正在执行代码',
        tool: 'execute',
        tool_input: {
          timeline: {
            step_type: 'tool',
            status: 'start',
            title: '执行代码',
            detail: 'python3 run.py',
          },
        },
      },
    }
    const secondStep: StreamEventResponse = {
      event: QueueEvent.deepStep,
      data: {
        id: 'step-1',
        event: QueueEvent.deepStep,
        thought: '执行完成',
        observation: 'exit_code=0',
        tool: 'execute',
        tool_input: {
          timeline: {
            step_type: 'tool',
            status: 'success',
            title: '执行代码',
            detail: '执行完成',
          },
        },
        latency: 2.4,
      },
    }

    state = applyChatStreamEvent(message, firstStep, state).state
    const result = applyChatStreamEvent(message, secondStep, state)

    expect(result.state.position).toBe(1)
    expect(message.agent_thoughts).toHaveLength(1)
    expect(message.agent_thoughts[0].thought).toBe('执行完成')
    expect(message.agent_thoughts[0].observation).toBe('exit_code=0')
    expect(message.agent_thoughts[0].latency).toBe(2.4)
  })

  it('records artifact created events as separate timeline items', () => {
    const message = createMessage()

    const result = applyChatStreamEvent(
      message,
      {
        event: QueueEvent.deepArtifactCreated,
        data: {
          id: 'artifact-1',
          event: QueueEvent.deepArtifactCreated,
          thought: 'trip-plan.docx',
          tool: 'artifact',
          tool_input: {
            artifact: {
              name: 'trip-plan.docx',
              url: 'https://example.com/trip-plan.docx',
            },
          },
        },
      },
      createState(),
    )

    expect(result.didUpdate).toBe(true)
    expect(message.agent_thoughts).toHaveLength(1)
    expect(message.agent_thoughts[0].event).toBe(QueueEvent.deepArtifactCreated)
    expect((message.agent_thoughts[0].tool_input as { artifact: { name: string } }).artifact.name).toBe('trip-plan.docx')
    expect(message.artifacts).toEqual([
      {
        name: 'trip-plan.docx',
        url: 'https://example.com/trip-plan.docx',
      },
    ])
    expect(message.answer_parts).toEqual([
      {
        type: 'artifact',
        name: 'trip-plan.docx',
        url: 'https://example.com/trip-plan.docx',
      },
    ])
  })

  it('records image artifact created events as image answer parts', () => {
    const message = createMessage()

    applyChatStreamEvent(
      message,
      {
        event: QueueEvent.deepArtifactCreated,
        data: {
          id: 'artifact-image-1',
          event: QueueEvent.deepArtifactCreated,
          thought: 'cover.png',
          tool: 'artifact',
          tool_input: {
            artifact: {
              name: 'cover.png',
              url: 'https://example.com/cover.png',
              extension: 'png',
              mime_type: 'image/png',
            },
          },
        },
      },
      createState(),
    )

    expect(message.artifacts).toEqual([
      {
        name: 'cover.png',
        url: 'https://example.com/cover.png',
        extension: 'png',
        mime_type: 'image/png',
      },
    ])
    expect(message.answer_parts).toEqual([
      {
        type: 'image',
        url: 'https://example.com/cover.png',
        name: 'cover.png',
        mime_type: 'image/png',
        extension: 'png',
      },
    ])
  })

  it('promotes inline image urls from agent action observations into gallery artifacts', () => {
    const message = createMessage()

    applyChatStreamEvent(
      message,
      {
        event: QueueEvent.agentAction,
        data: {
          id: 'tool-action-1',
          event: QueueEvent.agentAction,
          thought: '正在生成图片',
          observation: '✓ 成功生成图像\n图片 1:\n  URL: https://example.com/generated.png\n  提示: 图片已持久化保存，可直接访问和引用',
          tool: 'qwen_image_text_to_image',
          tool_input: {
            prompt: '上海历史建筑',
          },
        },
      },
      createState(),
    )

    expect(message.artifacts).toEqual([
      {
        name: '生成图片',
        url: 'https://example.com/generated.png',
      },
    ])
    expect(message.answer_parts).toEqual([
      {
        type: 'image',
        url: 'https://example.com/generated.png',
        name: '生成图片',
      },
    ])
  })

  it('extracts image parts from streamed answer text when only a URL is returned', () => {
    const message = createMessage()

    applyChatStreamEvent(
      message,
      {
        event: QueueEvent.agentMessage,
        data: {
          id: 'event-image',
          event: QueueEvent.agentMessage,
          thought: '图片 1:\n  URL: https://example.com/generated',
        },
      },
      createState(),
    )

    expect(message.answer_parts).toEqual([
      {
        type: 'text',
        text: '图片 1:\n  URL: https://example.com/generated',
      },
      {
        type: 'image',
        url: 'https://example.com/generated',
      },
    ])
  })

  it('overwrites answer on error event', () => {
    const message = createMessage()
    message.answer = 'previous'

    const result = applyChatStreamEvent(
      message,
      {
        event: QueueEvent.error,
        data: { observation: '执行失败' },
      },
      createState(),
    )

    expect(result.didUpdate).toBe(true)
    expect(message.answer).toBe('执行失败')
  })

  it('sets timeout fallback message on timeout event', () => {
    const message = createMessage()

    applyChatStreamEvent(
      message,
      {
        event: QueueEvent.timeout,
        data: {},
      },
      createState(),
    )

    expect(message.answer).toBe('当前Agent执行已超时，无法得到答案，请重试')
  })

  it('keeps render ids stable while preserving backend ids when available', () => {
    const tempMessage = withChatRenderId(createMessage(), 'debug-chat')
    const historyMessage = withChatRenderId(
      {
        ...createMessage(),
        id: 'message-1',
      },
      'debug-chat',
    )

    expect(tempMessage.render_id).toMatch(/^debug-chat-/)
    expect(historyMessage.render_id).toBe('message-1')
    expect(tempMessage.render_id).not.toBe(historyMessage.render_id)
  })

  it('merges overlapping history pages by message id without duplicating rows', () => {
    const firstPage = [
      withChatRenderId(
        {
          ...createMessage(),
          id: 'message-2',
        },
        'debug-chat',
      ),
      withChatRenderId(
        {
          ...createMessage(),
          id: 'message-1',
        },
        'debug-chat',
      ),
    ]
    const overlappingPage = [
      {
        ...createMessage(),
        id: 'message-1',
        render_id: 'stale-render-id',
      } as StreamMessage & { render_id: string },
      {
        ...createMessage(),
        id: 'message-0',
        render_id: 'older-render-id',
      } as StreamMessage & { render_id: string },
    ]

    const merged = mergeChatHistoryMessages([...firstPage, ...overlappingPage], 'debug-chat')

    expect(merged.map((item) => item.id)).toEqual(['message-2', 'message-1', 'message-0'])
    expect(merged.map((item) => item.render_id)).toEqual([
      'message-2',
      'message-1',
      'older-render-id',
    ])
  })

  it('stores deep thinking proposal in state without polluting thoughts', () => {
    const message = createMessage()
    const state = createState()

    const result = applyChatStreamEvent(
      message,
      {
        event: QueueEvent.deepThinkingProposal,
        data: {
          reason: '需要多步推理和沙箱执行',
          estimated_steps: 4,
        },
      },
      state,
    )

    expect(result.didUpdate).toBe(true)
    expect(result.state.deepThinkingProposal).toEqual({
      reason: '需要多步推理和沙箱执行',
      estimated_steps: 4,
    })
    expect(message.agent_thoughts).toHaveLength(0)
    expect(message.answer).toBe('')
  })

  it('billing_summary 事件应加入 billingEvents 数组', () => {
    const message = createMessage()
    const state = createState()

    const result = applyChatStreamEvent(
      message,
      {
        event: QueueEvent.billingSummary,
        data: {
          event: QueueEvent.billingSummary,
          source_type: 'summary',
          source_name: 'billing',
          delta_credits: 5,
          total_credits: 12,
          reason: 'mid_summary',
        } as NonNullable<StreamEventResponse['data']>,
      },
      state,
    )

    expect(result.didUpdate).toBe(true)
    expect(result.state.billingEvents).toHaveLength(1)
    expect(result.state.billingEvents[0].event).toBe(QueueEvent.billingSummary)
    expect(result.state.billingEvents[0].total_credits).toBe(12)
    expect(message.agent_thoughts).toHaveLength(0)
  })

  it('orchestrator_routing 事件不应产生空 thought', () => {
    const message = createMessage()
    const state = createState()

    const result = applyChatStreamEvent(
      message,
      {
        event: QueueEvent.orchestratorRouting,
        data: {
          intent: 'chat',
          execution_mode: 'direct_answer',
          complexity: 'low',
          recommended_model_tier: 'cheap',
          risk_level: 'safe',
          reason: 'simple query',
        } as NonNullable<StreamEventResponse['data']>,
      },
      state,
    )

    expect(result.didUpdate).toBe(true)
    expect(result.state.routingDecision).toEqual({
      intent: 'chat',
      execution_mode: 'direct_answer',
      complexity: 'low',
      recommended_model_tier: 'cheap',
      risk_level: 'safe',
      reason: 'simple query',
    })
    expect(message.agent_thoughts).toHaveLength(0)
    expect(message.answer).toBe('')
  })

  it('orchestrator_reject 事件应设置拒绝状态', () => {
    const message = createMessage()
    const state = createState()

    const result = applyChatStreamEvent(
      message,
      {
        event: QueueEvent.orchestratorReject,
        data: {
          reason: 'insufficient_balance',
          message: '余额不足，无法执行该请求',
        },
      },
      state,
    )

    expect(result.didUpdate).toBe(true)
    expect(result.state.orchestratorReject).toEqual({
      reason: 'insufficient_balance',
      message: '余额不足，无法执行该请求',
    })
    expect(message.agent_thoughts).toHaveLength(0)
    expect(message.answer).toBe('')
  })

  it('tool_confirmation_required 应使用确认记录 ID 而非事件 ID', () => {
    const message = createMessage()
    const state = createState()

    const result = applyChatStreamEvent(
      message,
      {
        event: QueueEvent.toolConfirmationRequired,
        data: {
          id: 'event-uuid',
          confirmation_id: 'confirm-123',
          tool: 'run_os_task',
          tool_input: { task: '清理 C 盘垃圾' },
          execution_summary: '预览计划',
          confirmation_status: 'pending',
        },
      },
      state,
    )

    expect(result.didUpdate).toBe(true)
    expect(result.state.toolConfirmationPrompt?.id).toBe('confirm-123')
    expect(result.state.toolConfirmationPrompt?.execution_summary).toBe('预览计划')
    expect(result.state.toolConfirmationPrompt?.status).toBe('pending')
    expect(message.agent_thoughts).toHaveLength(0)
  })

  it('run_os_task agent_action 应把执行结果回填到确认卡片', () => {
    const message = createMessage()
    let state = createState()
    state = applyChatStreamEvent(
      message,
      {
        event: QueueEvent.toolConfirmationRequired,
        data: {
          confirmation_id: 'confirm-123',
          tool: 'run_os_task',
          tool_input: { task: '清理 C 盘垃圾' },
          execution_summary: '预览计划',
          confirmation_status: 'pending',
        },
      },
      state,
    ).state

    const result = applyChatStreamEvent(
      message,
      {
        event: QueueEvent.agentAction,
        data: {
          id: 'action-1',
          tool: 'run_os_task',
          tool_input: { task: '清理 C 盘垃圾', mode: 'apply' },
          observation: '清理完成，释放 1.2GB',
        },
      },
      state,
    )

    expect(result.state.toolConfirmationPrompt?.execution_summary).toBe('清理完成，释放 1.2GB')
  })

  it('initializes subtasks and taskPlan on subtask_started event', () => {
    const message = createMessage()
    const state = createState()
    const event: StreamEventResponse = {
      event: QueueEvent.subtaskStarted,
      data: {
        id: 'msg-1',
        message_id: 'msg-1',
        conversation_id: 'conv-1',
        execution_mode: 'multi_agent_parallel',
        aggregation_strategy: 'summarize',
        reason: 'complex_query',
        task_count: 2,
        items: [
          {
            task_id: 'subtask_a',
            title: '搜索资料',
            description: '查找相关文档',
            depends_on: [],
            execution_order: 0,
            agent_id: 'agent_search',
            tools: ['search'],
            risk_level: 'safe',
            timeout_seconds: 30,
          },
          {
            task_id: 'subtask_b',
            title: '生成总结',
            description: '整合资料生成总结',
            depends_on: ['subtask_a'],
            execution_order: 1,
            agent_id: 'agent_writer',
            tools: [],
            risk_level: 'safe',
          },
        ],
      },
    }

    const result = applyChatStreamEvent(message, event, state)

    expect(result.didUpdate).toBe(true)
    expect(result.state.subtasks).toHaveLength(2)
    expect(result.state.subtasks?.[0]).toEqual({
      task_id: 'subtask_a',
      title: '搜索资料',
      status: 'pending',
      agent_id: 'agent_search',
      timeout_seconds: 30,
    })
    expect(result.state.subtasks?.[1].status).toBe('pending')
    expect(result.state.taskPlan).toEqual({
      execution_mode: 'multi_agent_parallel',
      aggregation_strategy: 'summarize',
      reason: 'complex_query',
      task_count: 2,
    })
    // subtask_started 不应该污染 agent_thoughts
    expect(message.agent_thoughts).toHaveLength(0)
  })

  it('updates subtask status to running on subtask_running event', () => {
    const message = createMessage()
    let state = createState()
    const startedResult = applyChatStreamEvent(
      message,
      {
        event: QueueEvent.subtaskStarted,
        data: {
          id: 'msg-1',
          message_id: 'msg-1',
          conversation_id: 'conv-1',
          execution_mode: 'multi_agent_parallel',
          aggregation_strategy: 'concat',
          reason: 'complex_query',
          task_count: 1,
          items: [
            {
              task_id: 'subtask_a',
              title: '搜索资料',
              description: '',
              depends_on: [],
              execution_order: 0,
              agent_id: 'agent_search',
              tools: [],
              risk_level: 'safe',
            },
          ],
        },
      },
      state,
    )
    state = startedResult.state

    const result = applyChatStreamEvent(
      message,
      {
        event: QueueEvent.subtaskRunning,
        data: {
          id: 'msg-1',
          task_id: 'subtask_a',
          agent_id: 'agent_search',
          status: 'running',
          conversation_id: 'conv-1',
          message_id: 'msg-1',
        },
      },
      state,
    )

    expect(result.didUpdate).toBe(true)
    expect(result.state.subtasks?.[0].status).toBe('running')
  })

  it('updates subtask status to completed on subtask_completed event', () => {
    const message = createMessage()
    let state = createState()
    // 先发 subtask_started 初始化
    const startedResult = applyChatStreamEvent(
      message,
      {
        event: QueueEvent.subtaskStarted,
        data: {
          id: 'msg-1',
          message_id: 'msg-1',
          conversation_id: 'conv-1',
          execution_mode: 'multi_agent_parallel',
          aggregation_strategy: 'summarize',
          reason: 'complex_query',
          task_count: 1,
          items: [
            {
              task_id: 'subtask_a',
              title: '搜索资料',
              description: '',
              depends_on: [],
              execution_order: 0,
              agent_id: 'agent_search',
              tools: [],
              risk_level: 'safe',
            },
          ],
        },
      },
      state,
    )
    state = startedResult.state

    // 再发 subtask_completed 更新状态
    const result = applyChatStreamEvent(
      message,
      {
        event: QueueEvent.subtaskCompleted,
        data: {
          id: 'subtask_a',
          task_id: 'subtask_a',
          conversation_id: 'conv-1',
          message_id: 'msg-1',
          agent_id: 'agent_search',
          status: 'completed',
          confidence: 0.92,
          answer_preview: '搜索完成，找到 3 个相关文档',
          errors: [],
        },
      },
      state,
    )

    expect(result.didUpdate).toBe(true)
    expect(result.state.subtasks).toHaveLength(1)
    expect(result.state.subtasks?.[0]).toEqual({
      task_id: 'subtask_a',
      title: '搜索资料',
      status: 'completed',
      agent_id: 'agent_search',
      answer_preview: '搜索完成，找到 3 个相关文档',
      confidence: 0.92,
      errors: [],
      timeout_seconds: 0,
    })
  })

  it('marks subtask as failed when status is failed', () => {
    const message = createMessage()
    let state = createState()
    const startedResult = applyChatStreamEvent(
      message,
      {
        event: QueueEvent.subtaskStarted,
        data: {
          id: 'msg-1',
          message_id: 'msg-1',
          conversation_id: 'conv-1',
          execution_mode: 'multi_agent_parallel',
          aggregation_strategy: 'summarize',
          reason: '',
          task_count: 1,
          items: [
            {
              task_id: 'subtask_x',
              title: '执行失败的任务',
              description: '',
              depends_on: [],
              execution_order: 0,
              agent_id: 'agent_x',
              tools: [],
              risk_level: 'safe',
            },
          ],
        },
      },
      state,
    )
    state = startedResult.state

    const result = applyChatStreamEvent(
      message,
      {
        event: QueueEvent.subtaskCompleted,
        data: {
          id: 'subtask_x',
          task_id: 'subtask_x',
          conversation_id: 'conv-1',
          message_id: 'msg-1',
          agent_id: 'agent_x',
          status: 'failed',
          confidence: 0,
          answer_preview: '',
          errors: ['tool_invocation_timeout'],
        },
      },
      state,
    )

    expect(result.state.subtasks?.[0].status).toBe('failed')
    expect(result.state.subtasks?.[0].errors).toEqual(['tool_invocation_timeout'])
  })

  it('extracts synthesis_meta from agent_message event', () => {
    const message = createMessage()
    const state = createState()
    const result = applyChatStreamEvent(
      message,
      {
        event: QueueEvent.agentMessage,
        data: {
          id: 'msg-1',
          message_id: 'msg-1',
          conversation_id: 'conv-1',
          answer: '综合后的最终答案',
          summary: '汇总了 3 个子任务的结论',
          confidence: 0.85,
          visible_sources: ['source_1', 'source_2'],
          user_warnings: ['部分子任务结果置信度较低'],
        },
      },
      state,
    )

    expect(result.didUpdate).toBe(true)
    expect(result.state.synthesisMeta).toEqual({
      summary: '汇总了 3 个子任务的结论',
      confidence: 0.85,
      visible_sources: ['source_1', 'source_2'],
      user_warnings: ['部分子任务结果置信度较低'],
    })
    expect(message.answer).toBe('综合后的最终答案')
  })
})
