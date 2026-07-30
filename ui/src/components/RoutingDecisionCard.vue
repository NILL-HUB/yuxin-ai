<script setup lang="ts">
import { computed } from 'vue'
import type { RoutingDecision } from '@/models/orchestration'

export type OrchestratorReject = {
  reason: string
  message: string
}

const props = defineProps<{
  decision: RoutingDecision | null
  reject?: OrchestratorReject | null
}>()

// 将原始 RoutingDecision 转换为可展示的扁平结构
const summary = computed(() => {
  const decision = props.decision
  if (!decision) return null
  const costPolicy = decision.cost_policy
  const agentSubset = decision.agent_subset
  const toolSubset = decision.tool_subset
  const selectedAgents = (agentSubset?.selected_agents as string[] | undefined) ?? []
  const selectedTools = (toolSubset?.selected_tools as string[] | undefined) ?? []
  return {
    intent: String(decision.intent ?? ''),
    execution_mode: String(decision.execution_mode ?? ''),
    complexity: String(decision.complexity ?? ''),
    recommended_model_tier: String(decision.recommended_model_tier ?? ''),
    risk_level: String(decision.risk_level ?? ''),
    needs_deep_thinking: Boolean(decision.needs_deep_thinking),
    cost_allowed: costPolicy ? Boolean(costPolicy.allowed) : null,
    max_agent_count: costPolicy ? Number(costPolicy.max_agent_count ?? 0) : null,
    max_tool_count: costPolicy ? Number(costPolicy.max_tool_count ?? 0) : null,
    selected_agents: selectedAgents,
    selected_tools: selectedTools,
  }
})
</script>

<template>
  <div v-if="summary || reject" class="space-y-2">
    <!-- 路由决策信息 -->
    <div
      v-if="summary"
      class="rounded-lg border border-blue-200 bg-blue-50/80 px-4 py-3 text-xs text-gray-700"
    >
      <div class="mb-1 font-medium text-gray-900">路由决策</div>
      <div class="flex flex-wrap gap-x-4 gap-y-1">
        <span><span class="text-gray-500">意图：</span>{{ summary.intent }}</span>
        <span><span class="text-gray-500">执行模式：</span>{{ summary.execution_mode }}</span>
        <span><span class="text-gray-500">复杂度：</span>{{ summary.complexity }}</span>
        <span><span class="text-gray-500">推荐档位：</span>{{ summary.recommended_model_tier }}</span>
        <span><span class="text-gray-500">风险等级：</span>{{ summary.risk_level }}</span>
        <span v-if="summary.needs_deep_thinking">
          <span class="text-gray-500">深度思考：</span>是
        </span>
        <span v-if="summary.cost_allowed !== null">
          <span class="text-gray-500">成本策略：</span>
          <a-tag :color="summary.cost_allowed ? 'green' : 'red'" size="small">
            {{ summary.cost_allowed ? '允许' : '拒绝' }}
          </a-tag>
        </span>
        <span v-if="summary.max_agent_count !== null">
          <span class="text-gray-500">最大Agent：</span>{{ summary.max_agent_count }}
        </span>
        <span v-if="summary.max_tool_count !== null">
          <span class="text-gray-500">最大工具：</span>{{ summary.max_tool_count }}
        </span>
      </div>
      <div
        v-if="summary.selected_agents.length > 0"
        class="mt-1 flex flex-wrap items-center gap-1"
      >
        <span class="text-gray-500">选中Agent：</span>
        <a-tag
          v-for="agent in summary.selected_agents"
          :key="agent"
          size="small"
          color="arcoblue"
        >
          {{ agent }}
        </a-tag>
      </div>
      <div
        v-if="summary.selected_tools.length > 0"
        class="mt-1 flex flex-wrap items-center gap-1"
      >
        <span class="text-gray-500">选中工具：</span>
        <a-tag
          v-for="tool in summary.selected_tools"
          :key="tool"
          size="small"
          color="cyan"
        >
          {{ tool }}
        </a-tag>
      </div>
    </div>

    <!-- 编排拒绝提示 -->
    <div
      v-if="reject"
      class="rounded-lg border border-red-200 bg-red-50/80 px-4 py-3 text-xs text-gray-700"
    >
      <div class="mb-1 font-medium text-red-900">编排拒绝</div>
      <div v-if="reject.message" class="break-words text-gray-800">{{ reject.message }}</div>
      <div v-if="reject.reason && reject.reason !== reject.message" class="mt-0.5 break-words text-gray-500">
        {{ reject.reason }}
      </div>
    </div>
  </div>
</template>
