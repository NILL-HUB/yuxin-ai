<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import type { AgentMetadata } from '@/models/app'

/**
 * 池治理字段编辑器：只负责 AgentMetadata 中的 4 个池治理字段
 * - primary_pool 主池（内置子池枚举）
 * - risk_level 风险等级（safe / medium / high）
 * - model_tier 模型档位（cheap / standard / strong）
 * - routing_priority 路由优先级（0-1000，默认 50）
 *
 * 其余字段由父组件持有并在提交时原样回传，本组件不修改。
 */
const model = defineModel<Partial<AgentMetadata>>({ required: true })

const { t } = useI18n()

// 内置子池列表（来自后端 api/internal/entity/agent_pool_entity.py 的 BUILTIN_AGENT_SUB_POOLS）
const PRIMARY_POOL_OPTIONS = [
  'general',
  'coding',
  'office',
  'data',
  'research',
  'customer_service',
  'internal_admin',
] as const

const RISK_LEVEL_OPTIONS: ReadonlyArray<'safe' | 'medium' | 'high'> = ['safe', 'medium', 'high']
const MODEL_TIER_OPTIONS: ReadonlyArray<'cheap' | 'standard' | 'strong'> = [
  'cheap',
  'standard',
  'strong',
]

const poolLabel = (pool: string) => {
  const map: Record<string, string> = {
    general: t('admin.apps.poolGeneral'),
    coding: t('admin.apps.poolCoding'),
    office: t('admin.apps.poolOffice'),
    data: t('admin.apps.poolData'),
    research: t('admin.apps.poolResearch'),
    customer_service: t('admin.apps.poolCustomerService'),
    internal_admin: t('admin.apps.poolInternalAdmin'),
  }
  return map[pool] || pool
}

const riskLabel = (risk: string) => {
  const map: Record<string, string> = {
    safe: t('admin.apps.riskSafe'),
    medium: t('admin.apps.riskMedium'),
    high: t('admin.apps.riskHigh'),
  }
  return map[risk] || risk
}

const tierLabel = (tier: string) => {
  const map: Record<string, string> = {
    cheap: t('admin.apps.modelCheap'),
    standard: t('admin.apps.modelStandard'),
    strong: t('admin.apps.modelStrong'),
  }
  return map[tier] || tier
}
</script>

<template>
  <a-form :model="model" layout="vertical">
    <a-form-item :label="t('admin.agentPool.primaryPool')" field="primary_pool">
      <a-select v-model="model.primary_pool" allow-search>
        <a-option v-for="pool in PRIMARY_POOL_OPTIONS" :key="pool" :value="pool">
          {{ poolLabel(pool) }}
        </a-option>
      </a-select>
    </a-form-item>
    <a-form-item :label="t('admin.agentPool.riskLevel')" field="risk_level">
      <a-select v-model="model.risk_level">
        <a-option v-for="risk in RISK_LEVEL_OPTIONS" :key="risk" :value="risk">
          {{ riskLabel(risk) }}
        </a-option>
      </a-select>
    </a-form-item>
    <a-form-item :label="t('admin.agentPool.modelTier')" field="model_tier">
      <a-select v-model="model.model_tier">
        <a-option v-for="tier in MODEL_TIER_OPTIONS" :key="tier" :value="tier">
          {{ tierLabel(tier) }}
        </a-option>
      </a-select>
    </a-form-item>
    <a-form-item :label="t('admin.agentPool.routingPriority')" field="routing_priority">
      <a-input-number v-model="model.routing_priority" :min="0" :max="1000" />
    </a-form-item>
  </a-form>
</template>
