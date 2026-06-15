<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import {
  getToolInventory,
  type ToolInventoryCandidate,
  type FilteredTool,
} from '@/services/tool-inventory'

const toolPool = ref('')
const riskLevel = ref('')
const candidates = ref<ToolInventoryCandidate[]>([])
const filteredOutTools = ref<FilteredTool[]>([])

const loadTools = async () => {
  const result = await getToolInventory({
    tool_pool: toolPool.value,
    risk_level: riskLevel.value,
  })
  candidates.value = result.candidates || []
  filteredOutTools.value = result.filtered_out_tools || []
}

onMounted(loadTools)
watch([toolPool, riskLevel], loadTools)
</script>

<template>
  <section class="admin-tools-view">
    <h2>工具治理</h2>
    <div class="filters">
      <label>
        工具分类
        <select v-model="toolPool" data-test="tool-pool-filter">
          <option value="">全部</option>
          <option value="mcp">mcp</option>
          <option value="api">api</option>
          <option value="builtin">builtin</option>
          <option value="knowledge">knowledge</option>
        </select>
      </label>
      <label>
        风险等级
        <select v-model="riskLevel" data-test="risk-filter">
          <option value="">全部</option>
          <option value="safe">safe</option>
          <option value="medium">medium</option>
          <option value="high">high</option>
        </select>
      </label>
    </div>
    <article v-for="tool in candidates" :key="tool.id" class="tool-card">
      <h3>{{ tool.name }}</h3>
      <dl>
        <dt>来源</dt>
        <dd>{{ tool.source_type }}</dd>
        <dt>分类</dt>
        <dd>{{ tool.metadata.tool_pool }}</dd>
        <dt>风险</dt>
        <dd>{{ tool.metadata.risk_level }}</dd>
        <dt>权限</dt>
        <dd>{{ tool.metadata.permission_scope }}</dd>
        <dt>可见性</dt>
        <dd>{{ tool.visibility }}</dd>
        <dt>健康状态</dt>
        <dd>{{ tool.metadata.health_status }}</dd>
      </dl>
    </article>
    <section v-if="filteredOutTools.length" class="filtered-tools">
      <h3>已过滤工具</h3>
      <p v-for="tool in filteredOutTools" :key="tool.id">
        {{ tool.name }}: {{ tool.reason }}
      </p>
    </section>
  </section>
</template>

<style scoped>
.admin-tools-view {
  display: grid;
  gap: 16px;
  padding: 24px;
}

.filters {
  display: flex;
  gap: 16px;
  flex-wrap: wrap;
}

label,
.tool-card,
.filtered-tools {
  display: grid;
  gap: 8px;
}

select {
  min-width: 160px;
  min-height: 32px;
  padding: 4px 8px;
  border: 1px solid #d1d5db;
  border-radius: 8px;
}

.tool-card,
.filtered-tools {
  max-width: 720px;
  padding: 16px;
  border: 1px solid #e5e7eb;
  border-radius: 12px;
}

dl {
  display: grid;
  grid-template-columns: 96px 1fr;
  gap: 8px;
}

dt {
  color: #6b7280;
}
</style>
