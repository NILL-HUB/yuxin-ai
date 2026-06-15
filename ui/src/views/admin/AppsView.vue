<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { type AgentMetadata } from '@/models/app'
import { listAdminApps, updateAdminAppMetadata } from '@/services/admin-apps'

type AdminApp = {
  id: string
  name: string
  agent_metadata?: AgentMetadata
}

const defaultMetadata: AgentMetadata = {
  primary_pool: 'general',
  secondary_pools: [],
  capabilities: [],
  task_types: [],
  input_modalities: ['text'],
  output_modalities: ['text'],
  risk_level: 'safe',
  model_tier: 'balanced',
  model_id: '',
  key_policy: 'default',
  cost_level: 'medium',
  routing_priority: 50,
  allowed_tool_categories: [],
  quality_score: 0.5,
  success_rate: 0,
  latency_p95: 0,
  max_context_tokens: 0,
  enabled: true,
}

const apps = ref<AdminApp[]>([])
const editableMetadata = ref<Record<string, AgentMetadata>>({})

const loadApps = async () => {
  const result = await listAdminApps({ page: 1, page_size: 20 }) as { list?: AdminApp[] }
  apps.value = result.list || []
  editableMetadata.value = Object.fromEntries(
    apps.value.map((app) => [app.id, { ...defaultMetadata, ...(app.agent_metadata || {}) }]),
  )
}

const saveMetadata = async (app: AdminApp) => {
  await updateAdminAppMetadata(app.id, editableMetadata.value[app.id])
}

onMounted(loadApps)
</script>

<template>
  <section class="admin-apps-view">
    <h2>应用管理</h2>
    <article v-for="app in apps" :key="app.id" class="app-card">
      <h3>{{ app.name }}</h3>
      <label>
        primary_pool
        <input v-model="editableMetadata[app.id].primary_pool" data-test="primary-pool" />
      </label>
      <label>
        risk_level
        <select v-model="editableMetadata[app.id].risk_level">
          <option value="safe">safe</option>
          <option value="medium">medium</option>
          <option value="high">high</option>
        </select>
      </label>
      <label>
        routing_priority
        <input v-model.number="editableMetadata[app.id].routing_priority" type="number" />
      </label>
      <label>
        enabled
        <input v-model="editableMetadata[app.id].enabled" type="checkbox" />
      </label>
      <button data-test="save-metadata" type="button" @click="saveMetadata(app)">
        保存元数据
      </button>
    </article>
  </section>
</template>

<style scoped>
.admin-apps-view {
  display: grid;
  gap: 16px;
  padding: 24px;
}

.app-card {
  display: grid;
  gap: 12px;
  max-width: 560px;
  padding: 16px;
  border: 1px solid #e5e7eb;
  border-radius: 12px;
}

label {
  display: grid;
  gap: 6px;
  color: #374151;
}

input,
select {
  min-height: 32px;
  padding: 4px 8px;
  border: 1px solid #d1d5db;
  border-radius: 8px;
}

button {
  width: fit-content;
  padding: 8px 12px;
  color: #ffffff;
  background: #111827;
  border: 0;
  border-radius: 8px;
}
</style>
