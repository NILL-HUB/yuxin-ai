<script setup lang="ts">
import { computed } from 'vue'

export type AiDataColumn = {
  key: string
  label: string
  align?: 'left' | 'center' | 'right'
  width?: string
}

const props = withDefaults(
  defineProps<{
    columns: AiDataColumn[]
    rows: Array<Record<string, unknown>>
    caption?: string
    emptyText?: string
  }>(),
  {
    columns: () => [],
    rows: () => [],
    caption: '',
    emptyText: 'No data',
  },
)

const hasRows = computed(() => props.rows.length > 0)

const formatCell = (value: unknown) => {
  if (value === null || value === undefined) return '-'
  if (typeof value === 'boolean') return value ? '是' : '否'
  if (typeof value === 'object') {
    try {
      return JSON.stringify(value)
    } catch {
      return String(value)
    }
  }
  return String(value)
}
</script>

<template>
  <div class="aicss-data-table" data-test="ai-data-table">
    <div v-if="caption" class="aicss-data-table__caption">{{ caption }}</div>
    <div class="aicss-data-table__scroll">
      <table class="aicss-data-table__table">
        <thead>
          <tr>
            <th
              v-for="column in columns"
              :key="column.key"
              :class="`aicss-data-table__cell aicss-data-table__cell--${column.align || 'left'}`"
              :style="column.width ? { width: column.width } : undefined"
            >
              {{ column.label }}
            </th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(row, rowIndex) in rows" :key="rowIndex">
            <td
              v-for="column in columns"
              :key="column.key"
              :class="`aicss-data-table__cell aicss-data-table__cell--${column.align || 'left'}`"
            >
              <span class="aicss-data-table__value">{{ formatCell(row[column.key]) }}</span>
            </td>
          </tr>
          <tr v-if="!hasRows">
            <td class="aicss-data-table__cell aicss-data-table__cell--center aicss-data-table__empty" :colspan="columns.length || 1">
              {{ emptyText }}
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<style scoped>
.aicss-data-table {
  width: 100%;
  max-width: 100%;
  min-width: 0;
  border-radius: var(--aicss-radius);
  border: 1px solid var(--aicss-border);
  background: var(--aicss-surface);
  box-shadow: var(--aicss-shadow-card);
  overflow: hidden;
  font-family: var(--aicss-font);
}

.aicss-data-table__caption {
  padding: 10px 14px;
  border-bottom: 1px solid var(--aicss-border);
  font-size: 13px;
  font-weight: 600;
  color: var(--aicss-text);
}

.aicss-data-table__scroll {
  width: 100%;
  overflow-x: auto;
  scrollbar-width: none;
}

.aicss-data-table__scroll::-webkit-scrollbar {
  display: none;
}

.aicss-data-table__table {
  width: 100%;
  min-width: 420px;
  border-collapse: collapse;
  font-size: 13px;
  line-height: 1.5;
}

.aicss-data-table__cell {
  padding: 9px 14px;
  text-align: left;
  white-space: nowrap;
}

.aicss-data-table__cell--center {
  text-align: center;
}

.aicss-data-table__cell--right {
  text-align: right;
}

thead .aicss-data-table__cell {
  position: sticky;
  top: 0;
  z-index: 1;
  background: var(--aicss-bg-subtle);
  color: var(--aicss-muted);
  font-size: 12px;
  font-weight: 600;
  border-bottom: 1px solid var(--aicss-border);
}

tbody .aicss-data-table__cell {
  color: var(--aicss-text-2);
  border-bottom: 1px solid var(--aicss-border);
}

tbody tr:last-child .aicss-data-table__cell {
  border-bottom: 0;
}

tbody tr:hover .aicss-data-table__cell {
  background: var(--aicss-surface-2);
}

.aicss-data-table__value {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.aicss-data-table__empty {
  padding: 28px 14px;
  color: var(--aicss-subtle);
}
</style>
