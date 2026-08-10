<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { Message } from '@arco-design/web-vue'
import { useI18n } from 'vue-i18n'
import { useAccountStore } from '@/stores/account'
import { getErrorMessage } from '@/utils/error'
import moment from 'moment'
import MemoryClusterView from '@/components/memory/MemoryClusterView.vue'
import MemoryGraphView from '@/components/memory/MemoryGraphView.vue'
import MemoryNodeDetail from '@/components/memory/MemoryNodeDetail.vue'
import {
  decayMemory,
  editMemory,
  getClusterSubgraph,
  getMemoryDetail,
  getMemoryDigest,
  getMemoryGraph,
  hardDeleteMemory,
  listSkills,
  softDeleteMemory,
  triggerConsolidation,
} from '@/services/memory-graph'
import type {
  ClusterSubgraph,
  MemoryDetail,
  MemoryGraphData,
  SkillInfo,
} from '@/models/memory-graph'

const { t } = useI18n()
const accountStore = useAccountStore()

// 当前用户 ID
const userId = computed(() => accountStore.account.id || '')

// Tab 切换：graph / digest / skills
const activeTab = ref('graph')

// ============ 图谱视图状态 ============
const graphData = ref<MemoryGraphData | null>(null)
const graphLoading = ref(false)
const selectedClusterType = ref<string>('')
const subgraph = ref<ClusterSubgraph | null>(null)
const subgraphLoading = ref(false)
const selectedNodeId = ref<string>('')
const nodeDetail = ref<MemoryDetail | null>(null)
const detailLoading = ref(false)

// ============ Digest 视图状态 ============
const digestText = ref('')
const digestLoading = ref(false)
const digestCached = ref(false)

// ============ 技能视图状态 ============
const skills = ref<SkillInfo[]>([])
const skillsLoading = ref(false)

// ============ 编辑弹窗 ============
const editModalVisible = ref(false)
const editContent = ref('')
const editSaving = ref(false)

// ============ 降权弹窗 ============
const decayModalVisible = ref(false)
const decayFactor = ref(0.5)
const decaySaving = ref(false)

// 加载图谱聚类数据
const loadGraph = async () => {
  if (!userId.value) return
  graphLoading.value = true
  try {
    graphData.value = await getMemoryGraph(userId.value)
  } catch (error) {
    Message.error(getErrorMessage(error, t('memory.graph.loadFailed')))
    graphData.value = null
  } finally {
    graphLoading.value = false
  }
}

// 选择聚类类型 → 加载子图
const handleSelectCluster = async (type: string) => {
  selectedClusterType.value = type
  subgraphLoading.value = true
  subgraph.value = null
  try {
    subgraph.value = await getClusterSubgraph(userId.value, type)
  } catch (error) {
    Message.error(getErrorMessage(error, t('memory.graph.loadFailed')))
    subgraph.value = null
  } finally {
    subgraphLoading.value = false
  }
}

// 选择节点 → 加载详情
const handleSelectNode = async (nodeId: string) => {
  selectedNodeId.value = nodeId
  detailLoading.value = true
  nodeDetail.value = null
  try {
    nodeDetail.value = await getMemoryDetail(nodeId)
  } catch (error) {
    Message.error(getErrorMessage(error, t('memory.graph.loadFailed')))
    nodeDetail.value = null
  } finally {
    detailLoading.value = false
  }
}

// 选择关联节点
const handleSelectRelated = (nodeId: string) => {
  handleSelectNode(nodeId)
}

// ============ CRUD 操作 ============

// 编辑记忆
const handleEdit = () => {
  if (!nodeDetail.value) return
  editContent.value = nodeDetail.value.content
  editModalVisible.value = true
}

const handleEditSave = async () => {
  const trimmed = editContent.value.trim()
  if (!trimmed || !selectedNodeId.value) return
  editSaving.value = true
  try {
    const resp = await editMemory(selectedNodeId.value, trimmed)
    if (resp.success) {
      Message.success(t('memory.graph.editSuccess'))
      editModalVisible.value = false
      // 重新加载详情和子图
      await Promise.all([
        handleSelectNode(selectedNodeId.value),
        selectedClusterType.value && handleSelectCluster(selectedClusterType.value),
      ])
    } else {
      Message.error(resp.error || t('memory.graph.editFailed'))
    }
  } catch (error) {
    Message.error(getErrorMessage(error, t('memory.graph.editFailed')))
  } finally {
    editSaving.value = false
  }
}

// 软删除
const handleSoftDelete = async () => {
  if (!selectedNodeId.value) return
  try {
    const resp = await softDeleteMemory(selectedNodeId.value)
    if (resp.deleted) {
      Message.success(t('memory.graph.softDeleteSuccess'))
      nodeDetail.value = null
      selectedNodeId.value = ''
      // 重新加载子图和图谱
      if (selectedClusterType.value) {
        await handleSelectCluster(selectedClusterType.value)
      }
      await loadGraph()
    } else {
      Message.error(t('memory.graph.deleteFailed'))
    }
  } catch (error) {
    Message.error(getErrorMessage(error, t('memory.graph.deleteFailed')))
  }
}

// 彻底删除
const handleHardDelete = async () => {
  if (!selectedNodeId.value) return
  try {
    const resp = await hardDeleteMemory(selectedNodeId.value)
    if (resp.deleted) {
      Message.success(t('memory.graph.hardDeleteSuccess'))
      nodeDetail.value = null
      selectedNodeId.value = ''
      if (selectedClusterType.value) {
        await handleSelectCluster(selectedClusterType.value)
      }
      await loadGraph()
    } else {
      Message.error(t('memory.graph.deleteFailed'))
    }
  } catch (error) {
    Message.error(getErrorMessage(error, t('memory.graph.deleteFailed')))
  }
}

// 降权
const handleDecay = () => {
  decayFactor.value = 0.5
  decayModalVisible.value = true
}

const handleDecaySave = async () => {
  if (!selectedNodeId.value) return
  decaySaving.value = true
  try {
    await decayMemory(selectedNodeId.value, decayFactor.value)
    Message.success(t('memory.graph.decaySuccess'))
    decayModalVisible.value = false
    await handleSelectNode(selectedNodeId.value)
  } catch (error) {
    Message.error(getErrorMessage(error, t('memory.graph.decayFailed')))
  } finally {
    decaySaving.value = false
  }
}

// ============ Digest ============
const loadDigest = async () => {
  if (!userId.value) return
  digestLoading.value = true
  try {
    const resp = await getMemoryDigest(userId.value)
    digestText.value = resp.digest || ''
    digestCached.value = resp.cached
  } catch (error) {
    Message.error(getErrorMessage(error, t('memory.graph.digestLoadFailed')))
    digestText.value = ''
  } finally {
    digestLoading.value = false
  }
}

// ============ 巩固 ============
const consolidating = ref(false)
const handleConsolidate = async () => {
  if (!userId.value) return
  consolidating.value = true
  try {
    const resp = await triggerConsolidation(userId.value)
    if (resp.success) {
      Message.success(
        t('memory.graph.consolidateSuccess', { count: resp.total_items }),
      )
      // 重新加载所有视图
      await loadGraph()
      if (selectedClusterType.value) {
        await handleSelectCluster(selectedClusterType.value)
      }
    } else {
      Message.error(t('memory.graph.consolidateFailed'))
    }
  } catch (error) {
    Message.error(getErrorMessage(error, t('memory.graph.consolidateFailed')))
  } finally {
    consolidating.value = false
  }
}

// ============ 技能 ============
const loadSkills = async () => {
  if (!userId.value) return
  skillsLoading.value = true
  try {
    const resp = await listSkills(userId.value)
    skills.value = resp.skills || []
  } catch (error) {
    Message.error(getErrorMessage(error, t('memory.graph.skillsLoadFailed')))
    skills.value = []
  } finally {
    skillsLoading.value = false
  }
}

// 技能状态颜色
const skillStatusColor = (status: string): string => {
  const map: Record<string, string> = {
    active: 'green',
    emerging: 'arcoblue',
    candidate: 'orange',
    stale: 'gray',
    deprecated: 'red',
  }
  return map[status] || 'gray'
}

const skillStatusLabel = (status: string): string => {
  const key = `memory.graph.skillStatus.${status}`
  const translated = t(key)
  return translated === key ? status : translated
}

// Tab 切换时按需加载
const handleTabChange = (key: string | number) => {
  const tabKey = String(key)
  if (tabKey === 'digest' && !digestText.value) {
    loadDigest()
  } else if (tabKey === 'skills' && skills.value.length === 0) {
    loadSkills()
  }
}

const formatTime = (value?: string) => {
  if (!value) return '-'
  const date = moment(value)
  return date.isValid() ? date.format('YYYY-MM-DD HH:mm') : value
}

onMounted(() => {
  loadGraph()
})
</script>

<template>
  <section class="space-y-4 p-6">
    <header class="flex items-start justify-between gap-4">
      <div>
        <h1 class="text-2xl font-semibold text-gray-900">{{ t('memory.graph.pageTitle') }}</h1>
        <p class="mt-1 text-sm text-gray-500">{{ t('memory.graph.pageDescription') }}</p>
      </div>
      <a-button
        type="primary"
        :loading="consolidating"
        data-test="consolidate-btn"
        @click="handleConsolidate"
      >
        <template #icon>
          <icon-refresh />
        </template>
        {{ t('memory.graph.consolidateBtn') }}
      </a-button>
    </header>

    <a-tabs v-model:active-key="activeTab" type="rounded" @change="handleTabChange">
      <!-- 图谱视图 Tab -->
      <a-tab-pane key="graph" :title="t('memory.graph.graphTab')">
        <div class="space-y-4">
          <!-- 聚类视图 -->
          <MemoryClusterView
            :clusters="graphData?.clusters || []"
            :loading="graphLoading"
            :selected-type="selectedClusterType"
            data-test="cluster-view"
            @select-cluster="handleSelectCluster"
          />

          <!-- 子图 + 详情联动布局 -->
          <div class="grid gap-4 lg:grid-cols-3">
            <!-- 力导向子图（占 2 列） -->
            <div class="lg:col-span-2">
              <div v-if="!selectedClusterType" class="flex h-[500px] items-center justify-center rounded-lg border bg-white text-gray-400">
                <div class="text-center">
                  <icon-bookmark class="mb-3 text-5xl" />
                  <p>{{ t('memory.graph.selectClusterHint') }}</p>
                </div>
              </div>
              <MemoryGraphView
                v-else
                :subgraph="subgraph"
                :loading="subgraphLoading"
                data-test="graph-view"
                @select-node="handleSelectNode"
              />
            </div>

            <!-- 节点详情面板（占 1 列） -->
            <div class="rounded-lg border bg-white">
              <MemoryNodeDetail
                :detail="nodeDetail"
                :loading="detailLoading"
                data-test="node-detail"
                @edit="handleEdit"
                @soft-delete="handleSoftDelete"
                @hard-delete="handleHardDelete"
                @decay="handleDecay"
                @select-related="handleSelectRelated"
              />
            </div>
          </div>
        </div>
      </a-tab-pane>

      <!-- Digest Tab -->
      <a-tab-pane key="digest" :title="t('memory.graph.digestTab')">
        <div class="rounded-lg border bg-white p-6">
          <div class="mb-3 flex items-center justify-between">
            <span class="text-sm font-medium text-gray-700">{{ t('memory.graph.digestTitle') }}</span>
            <div class="flex items-center gap-2">
              <a-tag v-if="digestCached" size="small" color="arcoblue">
                {{ t('memory.graph.cached') }}
              </a-tag>
              <a-button size="small" :loading="digestLoading" @click="loadDigest">
                <template #icon><icon-refresh /></template>
                {{ t('memory.graph.refreshDigest') }}
              </a-button>
            </div>
          </div>
          <a-spin :loading="digestLoading" class="block">
            <div v-if="digestText" class="whitespace-pre-wrap text-sm leading-relaxed text-gray-700">
              {{ digestText }}
            </div>
            <div v-else class="py-8 text-center text-gray-400">
              {{ t('memory.graph.digestEmpty') }}
            </div>
          </a-spin>
        </div>
      </a-tab-pane>

      <!-- 技能 Tab -->
      <a-tab-pane key="skills" :title="t('memory.graph.skillsTab')">
        <a-spin :loading="skillsLoading" class="block">
          <div v-if="!skillsLoading && skills.length === 0" class="flex flex-col items-center justify-center py-16 text-gray-400">
            <icon-bulb class="mb-3 text-5xl" />
            <p>{{ t('memory.graph.skillsEmpty') }}</p>
          </div>
          <div v-else class="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            <div
              v-for="(skill, idx) in skills"
              :key="idx"
              class="rounded-lg border bg-white p-4"
            >
              <div class="mb-2 flex items-center justify-between">
                <span class="font-medium text-gray-800">{{ skill.name }}</span>
                <a-tag :color="skillStatusColor(skill.status)" size="small">
                  {{ skillStatusLabel(skill.status) }}
                </a-tag>
              </div>
              <p v-if="skill.description" class="mb-2 text-sm text-gray-600">
                {{ skill.description }}
              </p>
              <div class="flex flex-wrap gap-3 text-xs text-gray-400">
                <span v-if="skill.maturity !== undefined">
                  {{ t('memory.graph.maturity') }}：{{ (skill.maturity * 100).toFixed(0) }}%
                </span>
                <span v-if="skill.use_count !== undefined">
                  {{ t('memory.graph.useCount') }}：{{ skill.use_count }}
                </span>
                <span v-if="skill.frequency !== undefined">
                  {{ t('memory.graph.frequency') }}：{{ skill.frequency }}
                </span>
              </div>
              <div v-if="skill.last_updated_at" class="mt-2 text-xs text-gray-300">
                {{ formatTime(skill.last_updated_at) }}
              </div>
            </div>
          </div>
        </a-spin>
      </a-tab-pane>
    </a-tabs>

    <!-- 编辑弹窗 -->
    <a-modal
      v-model:visible="editModalVisible"
      :title="t('memory.graph.editTitle')"
      :ok-text="t('common.actions.save')"
      :cancel-text="t('common.actions.cancel')"
      :ok-loading="editSaving"
      @ok="handleEditSave"
      @cancel="editModalVisible = false"
    >
      <a-form layout="vertical" :model="{}">
        <a-form-item :label="t('memory.graph.contentLabel')">
          <a-textarea
            v-model="editContent"
            :auto-size="{ minRows: 4, maxRows: 8 }"
            :placeholder="t('memory.graph.contentPlaceholder')"
          />
        </a-form-item>
      </a-form>
    </a-modal>

    <!-- 降权弹窗 -->
    <a-modal
      v-model:visible="decayModalVisible"
      :title="t('memory.graph.decayTitle')"
      :ok-text="t('common.actions.confirm')"
      :cancel-text="t('common.actions.cancel')"
      :ok-loading="decaySaving"
      @ok="handleDecaySave"
      @cancel="decayModalVisible = false"
    >
      <a-form layout="vertical" :model="{}">
        <a-form-item :label="t('memory.graph.decayFactorLabel')">
          <a-slider v-model="decayFactor" :min="0" :max="1" :step="0.1" show-input />
        </a-form-item>
      </a-form>
    </a-modal>
  </section>
</template>
