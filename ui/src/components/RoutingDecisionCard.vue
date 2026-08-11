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
      class="aicss-routing-card"
    >
      <div class="aicss-routing-card__title">路由决策</div>
      <div class="aicss-routing-card__grid">
        <span class="aicss-routing-card__item"><span class="aicss-routing-card__label">意图：</span>{{ summary.intent }}</span>
        <span class="aicss-routing-card__item"><span class="aicss-routing-card__label">执行模式：</span>{{ summary.execution_mode }}</span>
        <span class="aicss-routing-card__item"><span class="aicss-routing-card__label">复杂度：</span>{{ summary.complexity }}</span>
        <span class="aicss-routing-card__item"><span class="aicss-routing-card__label">推荐档位：</span>{{ summary.recommended_model_tier }}</span>
        <span class="aicss-routing-card__item"><span class="aicss-routing-card__label">风险等级：</span>{{ summary.risk_level }}</span>
        <span v-if="summary.needs_deep_thinking">
          <span class="aicss-routing-card__label">深度思考：</span>是
        </span>
        <span v-if="summary.cost_allowed !== null">
          <span class="aicss-routing-card__label">成本策略：</span>
          <span class="aicss-routing-card__pill" :class="summary.cost_allowed ? 'aicss-routing-card__pill--ok' : 'aicss-routing-card__pill--no'">
            {{ summary.cost_allowed ? '允许' : '拒绝' }}
          </span>
        </span>
        <span v-if="summary.max_agent_count !== null">
          <span class="aicss-routing-card__label">最大Agent：</span>{{ summary.max_agent_count }}
        </span>
        <span v-if="summary.max_tool_count !== null">
          <span class="aicss-routing-card__label">最大工具：</span>{{ summary.max_tool_count }}
        </span>
      </div>
      <div
        v-if="summary.selected_agents.length > 0"
        class="aicss-routing-card__tags"
      >
        <span class="aicss-routing-card__label">选中Agent：</span>
        <span
          v-for="agent in summary.selected_agents"
          :key="agent"
          class="aicss-routing-card__tag"
        >
          {{ agent }}
        </span>
      </div>
      <div
        v-if="summary.selected_tools.length > 0"
        class="aicss-routing-card__tags"
      >
        <span class="aicss-routing-card__label">选中工具：</span>
        <span
          v-for="tool in summary.selected_tools"
          :key="tool"
          class="aicss-routing-card__tag"
        >
          {{ tool }}
        </span>
      </div>
    </div>

    <!-- 编排拒绝提示 -->
    <div
      v-if="reject"
      class="aicss-routing-card aicss-routing-card--reject"
    >
      <div class="aicss-routing-card__title">编排拒绝</div>
      <div v-if="reject.message" class="aicss-routing-card__reject-message">{{ reject.message }}</div>
      <div v-if="reject.reason && reject.reason !== reject.message" class="aicss-routing-card__reject-reason">
        {{ reject.reason }}
      </div>
    </div>
  </div>
</template>

<style scoped>
.aicss-routing-card {
  width: 100%;
  max-width: 100%;
  padding: 12px 14px;
  border-radius: 10px;
  background: var(--aicss-surface);
  border: 1px solid var(--aicss-border);
  box-shadow: var(--aicss-shadow-card);
  font-size: 12px;
  line-height: 1.55;
  color: var(--aicss-text-2);
}

.aicss-routing-card--reject {
  border-color: color-mix(in srgb, var(--aicss-danger) 32%, var(--aicss-border));
  background: color-mix(in srgb, var(--aicss-danger-soft) 48%, var(--aicss-surface));
}

.aicss-routing-card__title {
  margin-bottom: 6px;
  font-weight: 650;
  color: var(--aicss-text);
}

.aicss-routing-card__grid {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 14px;
}

.aicss-routing-card__item {
  color: var(--aicss-text-2);
}

.aicss-routing-card__label {
  color: var(--aicss-muted);
}

.aicss-routing-card__pill {
  display: inline-flex;
  align-items: center;
  padding: 1px 8px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 550;
}

.aicss-routing-card__pill--ok {
  background: var(--aicss-success-soft);
  color: var(--aicss-success);
}

.aicss-routing-card__pill--no {
  background: var(--aicss-danger-soft);
  color: var(--aicss-danger);
}

.aicss-routing-card__tags {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 5px;
  margin-top: 6px;
}

.aicss-routing-card__tag {
  display: inline-flex;
  align-items: center;
  padding: 1px 8px;
  border-radius: 6px;
  background: var(--aicss-accent-soft);
  color: var(--aicss-accent-text);
  font-size: 11px;
  font-weight: 500;
}

.aicss-routing-card__reject-message {
  color: var(--aicss-text);
  overflow-wrap: anywhere;
}

.aicss-routing-card__reject-reason {
  margin-top: 2px;
  color: var(--aicss-muted);
  overflow-wrap: anywhere;
}
</style>
