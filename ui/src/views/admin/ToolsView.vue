<script setup lang="ts">
import { Message } from '@arco-design/web-vue'
import { onMounted, ref } from 'vue'
import type { AdminToolRecord } from '@/models/admin-tool'
import { listAdminTools } from '@/services/admin-tools'
import { getErrorMessage } from '@/utils/error'

const keyword = ref('')
const loading = ref(false)
const tools = ref<AdminToolRecord[]>([])
const totalRecord = ref(0)

/**
 * 加载后台 API 工具治理入口的分页数据。
 */
const loadTools = async () => {
  loading.value = true
  try {
    const result = await listAdminTools({
      current_page: 1,
      page_size: 20,
      keyword: keyword.value.trim(),
    })
    tools.value = result.list || []
    totalRecord.value = result.paginator?.total_record || 0
  } catch (error) {
    Message.error(getErrorMessage(error, '加载 API 工具治理数据失败'))
  } finally {
    loading.value = false
  }
}

/**
 * 触发关键字搜索并刷新第一页数据。
 */
const handleSearch = async () => {
  await loadTools()
}

/**
 * 格式化允许使用的工具池列表。
 */
const formatPools = (allowedPools: string[]) => {
  return allowedPools.length ? allowedPools.join(', ') : '-'
}

/**
 * 格式化治理策略更新时间。
 */
const formatUpdatedAt = (timestamp?: number) => {
  return timestamp ? new Date(timestamp * 1000).toLocaleString() : '-'
}

onMounted(() => {
  void loadTools()
})
</script>

<template>
  <section class="admin-tools-view">
    <header class="page-header">
      <div>
        <h2>API工具治理</h2>
        <p>查看 `/admin/tools` 返回的 API Tool 治理策略列表与启用状态。</p>
      </div>
      <a href="/admin/tool-governance" class="governance-link">进入完整治理中心</a>
    </header>

    <section class="toolbar">
      <input
        v-model="keyword"
        data-test="keyword-filter"
        type="text"
        placeholder="搜索工具名称或 tool_id"
        @keyup.enter="handleSearch"
      />
      <button type="button" data-test="search-button" @click="handleSearch">搜索</button>
      <span class="summary">共 {{ totalRecord }} 条</span>
    </section>

    <p v-if="loading" class="state-text">加载中...</p>
    <p v-else-if="!tools.length" class="state-text">暂无 API 工具治理策略</p>

    <section v-else class="tool-list">
      <article v-for="tool in tools" :key="tool.id" class="tool-card">
        <div class="tool-card__header">
          <div>
            <h3>{{ tool.tool_name }}</h3>
            <p class="tool-id">{{ tool.tool_id }}</p>
          </div>
          <span :class="['status-badge', tool.enabled ? 'status-badge--enabled' : 'status-badge--disabled']">
            {{ tool.enabled ? '启用中' : '已停用' }}
          </span>
        </div>

        <p v-if="tool.description" class="description">{{ tool.description }}</p>

        <dl>
          <dt>来源类型</dt>
          <dd>{{ tool.source_type }}</dd>
          <dt>风险等级</dt>
          <dd>{{ tool.risk_level }}</dd>
          <dt>可见性</dt>
          <dd>{{ tool.visibility }}</dd>
          <dt>允许池</dt>
          <dd>{{ formatPools(tool.allowed_pools || []) }}</dd>
          <dt>单请求上限</dt>
          <dd>{{ tool.max_invocations_per_request }}</dd>
          <dt>冷却时间</dt>
          <dd>{{ tool.cooldown_seconds }} 秒</dd>
          <dt>确认要求</dt>
          <dd>{{ tool.require_confirmation ? '需要确认' : '无需确认' }}</dd>
          <dt>更新时间</dt>
          <dd>{{ formatUpdatedAt(tool.updated_at) }}</dd>
        </dl>
      </article>
    </section>
  </section>
</template>

<style scoped>
.admin-tools-view {
  display: grid;
  gap: 20px;
  padding: 24px;
}

.page-header {
  display: flex;
  gap: 16px;
  align-items: flex-start;
  justify-content: space-between;
  flex-wrap: wrap;
}

.page-header h2 {
  margin: 0;
  font-size: 28px;
  line-height: 1.2;
  color: #111827;
}

.page-header p {
  margin: 8px 0 0;
  color: #6b7280;
}

.governance-link {
  color: #2563eb;
  text-decoration: none;
  font-weight: 600;
}

.toolbar {
  display: flex;
  gap: 12px;
  align-items: center;
  flex-wrap: wrap;
}

.toolbar input {
  min-width: 280px;
  min-height: 40px;
  padding: 0 12px;
  border: 1px solid #d1d5db;
  border-radius: 10px;
}

.toolbar button {
  min-height: 40px;
  padding: 0 16px;
  border: 0;
  border-radius: 10px;
  background: #111827;
  color: #ffffff;
  cursor: pointer;
}

.summary,
.state-text,
.tool-id,
.description,
dt {
  color: #6b7280;
}

.tool-list {
  display: grid;
  gap: 16px;
  grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
}

.tool-card {
  display: grid;
  gap: 12px;
  padding: 20px;
  border: 1px solid #e5e7eb;
  border-radius: 16px;
  background: #ffffff;
}

.tool-card__header {
  display: flex;
  gap: 12px;
  align-items: flex-start;
  justify-content: space-between;
}

.tool-card__header h3 {
  margin: 0;
  font-size: 20px;
  color: #111827;
}

.tool-id,
.description {
  margin: 0;
}

.status-badge {
  padding: 4px 10px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 600;
}

.status-badge--enabled {
  background: #dcfce7;
  color: #166534;
}

.status-badge--disabled {
  background: #fee2e2;
  color: #991b1b;
}

dl {
  display: grid;
  grid-template-columns: 96px 1fr;
  gap: 8px 12px;
  margin: 0;
}

dd {
  margin: 0;
  color: #111827;
}
</style>
