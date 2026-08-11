<script setup lang="ts">
import { computed } from 'vue'

export type AiComparisonColumn = {
  key: string
  label: string
}

export type AiComparisonRow = {
  label: string
  values: Array<boolean | string | number>
}

const props = withDefaults(
  defineProps<{
    columns: AiComparisonColumn[]
    rows: AiComparisonRow[]
    emptyText?: string
  }>(),
  {
    columns: () => [],
    rows: () => [],
    emptyText: '—',
  },
)

const hasRows = computed(() => props.rows.length > 0)

const formatValue = (value: boolean | string | number) => {
  if (typeof value === 'boolean') return ''
  return String(value ?? props.emptyText)
}
</script>

<template>
  <div class="aicss-comparison-table" data-test="ai-comparison-table">
    <div class="aicss-comparison-table__scroll">
      <table class="aicss-comparison-table__table">
        <thead>
          <tr>
            <th class="aicss-comparison-table__cell aicss-comparison-table__feature">Feature</th>
            <th
              v-for="column in columns"
              :key="column.key"
              class="aicss-comparison-table__cell aicss-comparison-table__plan"
            >
              {{ column.label }}
            </th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in rows" :key="row.label">
            <td class="aicss-comparison-table__cell aicss-comparison-table__feature">
              <span class="aicss-comparison-table__label">{{ row.label }}</span>
            </td>
            <td
              v-for="(value, index) in row.values"
              :key="index"
              class="aicss-comparison-table__cell aicss-comparison-table__plan"
            >
              <span
                v-if="typeof value === 'boolean'"
                class="aicss-comparison-table__mark"
                :class="value ? 'aicss-comparison-table__mark--yes' : 'aicss-comparison-table__mark--no'"
              >
                {{ value ? '✓' : '—' }}
              </span>
              <span v-else class="aicss-comparison-table__text">{{ formatValue(value) }}</span>
            </td>
          </tr>
          <tr v-if="!hasRows">
            <td class="aicss-comparison-table__cell aicss-comparison-table__empty" :colspan="columns.length + 1">
              暂无对比数据
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<style scoped>
.aicss-comparison-table {
  width: 100%;
  max-width: 100%;
  min-width: 0;
  border-radius: var(--aicss-radius);
  border: 1px solid var(--aicss-border);
  background: var(--aicss-bg-subtle);
  box-shadow: var(--aicss-shadow-card);
  overflow: hidden;
  font-family: var(--aicss-font);
  font-size: 13px;
}

.aicss-comparison-table__scroll {
  width: 100%;
  overflow-x: auto;
  scrollbar-width: none;
}

.aicss-comparison-table__scroll::-webkit-scrollbar {
  display: none;
}

.aicss-comparison-table__table {
  width: 100%;
  min-width: 420px;
  border-collapse: separate;
  border-spacing: 0;
}

.aicss-comparison-table__cell {
  padding: 10px 14px;
  text-align: center;
  white-space: nowrap;
  border-bottom: 1px solid var(--aicss-border);
}

.aicss-comparison-table__feature {
  text-align: left;
  background: var(--aicss-bg-subtle);
  color: var(--aicss-muted);
}

.aicss-comparison-table__plan {
  background: var(--aicss-surface);
  color: var(--aicss-text);
}

thead .aicss-comparison-table__cell {
  color: var(--aicss-muted);
  font-size: 12px;
  font-weight: 600;
}

tbody tr:last-child .aicss-comparison-table__cell {
  border-bottom: 0;
}

.aicss-comparison-table__label {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.aicss-comparison-table__mark {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 20px;
  height: 20px;
  border-radius: 50%;
  font-size: 12px;
  line-height: 1;
}

.aicss-comparison-table__mark--yes {
  background: var(--aicss-success-soft);
  color: var(--aicss-success);
}

.aicss-comparison-table__mark--no {
  background: var(--aicss-surface-2);
  color: var(--aicss-subtle);
}

.aicss-comparison-table__text {
  color: var(--aicss-text-2);
}

.aicss-comparison-table__empty {
  padding: 28px 14px;
  color: var(--aicss-subtle);
}
</style>
