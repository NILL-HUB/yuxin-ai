<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { Message } from '@arco-design/web-vue'
import { useI18n } from 'vue-i18n'
import { useAccountStore } from '@/stores/account'
import { useMarkdownRenderer } from '@/hooks/use-markdown-renderer'
import { getErrorMessage } from '@/utils/error'
import moment from 'moment'
import RecycleBinDeleteModal from '@/components/recycle-bin/UserRecycleBinDeleteModal.vue'
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
// 本次会话内是否已请求过摘要：避免每次切 tab / 打开页面都重复请求后端
const digestLoadedOnce = ref(false)

// markdown 渲染（摘要由 LLM 生成，后端存 md 原文）
const { renderMarkdown, handleMarkdownCopyClick } = useMarkdownRenderer()
const digestHtml = computed(() => (digestText.value ? renderMarkdown(digestText.value) : ''))
const handleDigestClick = async (event: MouseEvent) => {
  await handleMarkdownCopyClick(event, { successMessage: t('chat.messages.codeCopied') })
}

// ============ 技能视图状态 ============
const skills = ref<SkillInfo[]>([])
const skillsLoading = ref(false)

// ============ 编辑弹窗 ============
const editModalVisible = ref(false)
const editContent = ref('')
const editSaving = ref(false)

// ============ 降权（详情面板内联滑杆） ============
const decayFactor = ref(0.5)
const decaySaving = ref(false)

// ============ 软删确认弹窗（进入回收站 + 选择留存天数） ============
const softDeleteModalVisible = ref(false)
const softDeleteSaving = ref(false)

// 聚类 chips：后端 memory_type → 前端展示名（与原型"主题聚类"一致）
const CLUSTER_LABEL: Record<string, string> = {
  entity: '实体记忆',
  episode: '情景记忆',
  event: '事件',
  preference: '偏好',
  profile: '个人资料',
  project: '项目',
  relationship: '关系',
  secret: '机密',
  habit: '习惯',
  goal: '目标',
  identity: '身份',
  capability: '能力',
  confidential: '机密信息',
}
const clusterChips = computed(() => {
  const list = graphData.value?.clusters ?? []
  // 按节点数降序，保证活跃聚类靠前
  const sorted = [...list].sort((a, b) => b.node_count - a.node_count)
  return sorted.map((c) => ({
    type: c.memory_type,
    label: CLUSTER_LABEL[c.memory_type] || c.memory_type,
    count: c.node_count,
  }))
})
const totalNodeCount = computed(() => graphData.value?.total_nodes ?? 0)

// 加载图谱聚类数据
const loadGraph = async () => {
  const uid = userId.value
  if (!uid || graphLoading.value) return
  graphLoading.value = true
  try {
    graphData.value = await getMemoryGraph(uid)
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
  selectedNodeId.value = ''
  nodeDetail.value = null
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
      // 内容已变更 → 重置摘要加载标记
      resetDigestLoadState()
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

// 软删除（弹出确认框，进入回收站 + 选择留存天数）
const handleSoftDelete = () => {
  if (!selectedNodeId.value) return
  softDeleteModalVisible.value = true
}

const confirmSoftDelete = async (retentionDays: number) => {
  if (!selectedNodeId.value) return
  softDeleteSaving.value = true
  try {
    const resp = await softDeleteMemory(selectedNodeId.value, retentionDays)
    if (resp.deleted) {
      Message.success(t('memory.graph.softDeleteSuccess'))
      softDeleteModalVisible.value = false
      nodeDetail.value = null
      selectedNodeId.value = ''
      // 内容已变更 → 重置摘要加载标记
      resetDigestLoadState()
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
  } finally {
    softDeleteSaving.value = false
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
      // 内容已变更 → 重置摘要加载标记
      resetDigestLoadState()
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

// 降权（详情面板内联滑杆触发）
const handleDecay = () => {
  decayFactor.value = 0.5
}

const handleDecaySave = async (factor: number) => {
  if (!selectedNodeId.value) return
  decaySaving.value = true
  try {
    await decayMemory(selectedNodeId.value, factor)
    Message.success(t('memory.graph.decaySuccess'))
    await handleSelectNode(selectedNodeId.value)
  } catch (error) {
    Message.error(getErrorMessage(error, t('memory.graph.decayFailed')))
  } finally {
    decaySaving.value = false
  }
}

// ============ Digest ============
// refresh=false 读缓存（切 tab 触发）；refresh=true 强制重新生成（仅"刷新摘要"按钮触发）
const loadDigest = async (refresh = false) => {
  if (!userId.value || digestLoading.value) return
  // 非强制刷新时：本次会话已请求过就不再重复请求（内容变更由后端失效缓存驱动）
  if (!refresh && digestLoadedOnce.value) return
  digestLoading.value = true
  try {
    const resp = await getMemoryDigest(userId.value, refresh)
    digestText.value = resp.digest || ''
    digestCached.value = resp.cached
  } catch (error) {
    Message.error(getErrorMessage(error, t('memory.graph.digestLoadFailed')))
    digestText.value = ''
  } finally {
    digestLoadedOnce.value = true
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
      // 内容已变更 → 重置摘要加载标记，下次切到摘要 tab 拉取最新
      resetDigestLoadState()
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
const skillStatusCls = (status: string): string => {
  const map: Record<string, string> = {
    active: 'st-active',
    emerging: 'st-emerging',
    candidate: 'st-candidate',
    stale: 'st-stale',
    deprecated: 'st-deprecated',
  }
  return map[status] || 'st-stale'
}

const skillStatusLabel = (status: string): string => {
  const key = `memory.graph.skillStatus.${status}`
  const translated = t(key)
  return translated === key ? status : translated
}

// Tab 切换时按需加载
const handleTabChange = (key: string) => {
  if (key === 'digest') {
    loadDigest()
  } else if (key === 'skills' && skills.value.length === 0) {
    loadSkills()
  }
}

// 记忆内容变更（写入/编辑/巩固等）后重置摘要加载标记，
// 下次切换到摘要 tab 时自动拉取后端失效后重建的最新摘要
const resetDigestLoadState = () => {
  digestLoadedOnce.value = false
}

const formatTime = (value?: string) => {
  if (!value) return '-'
  const date = moment(value)
  return date.isValid() ? date.format('YYYY-MM-DD HH:mm') : value
}

// account.id 由布局层异步拉取后写入：id 就绪且未加载过 → 自动加载图谱
watch(
  () => accountStore.account.id,
  (id) => {
    if (id && !graphData.value && !graphLoading.value) {
      loadGraph()
    }
  },
  { immediate: true },
)
</script>

<template>
  <div class="mem-page h-full w-full overflow-y-auto">
    <div class="mx-auto w-full max-w-6xl px-4 py-6 sm:px-6 lg:px-8 lg:py-8">
      <!-- ===== 页头区（对齐原型 memory.html） ===== -->
      <header class="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <h1 class="mem-title text-3xl font-bold tracking-tight sm:text-4xl">记忆空间</h1>
          <p class="mt-2 text-sm text-muted">{{ t('memory.graph.pageDescription') }}</p>
        </div>
        <div class="flex flex-col gap-3 sm:flex-row sm:items-center">
          <button
            type="button"
            class="kb-btn kb-btn-primary h-10"
            :class="{ 'is-loading': consolidating }"
            :disabled="consolidating"
            data-test="consolidate-btn"
            @click="handleConsolidate"
          >
            <icon-refresh v-if="!consolidating" class="kb-btn-ico" />
            {{ consolidating ? '巩固中…' : '巩固记忆' }}
          </button>
          <button
            v-if="activeTab === 'digest'"
            type="button"
            class="kb-btn kb-btn-ghost h-10"
            :class="{ 'is-loading': digestLoading }"
            :disabled="digestLoading"
            @click="loadDigest(true)"
          >
            <icon-refresh v-if="!digestLoading" class="kb-btn-ico" />
            刷新摘要
          </button>
        </div>
      </header>

      <!-- ===== Tab 栏（下划线式，对齐原型） ===== -->
      <div class="mem-tabs" role="tablist" aria-label="记忆空间视图">
        <button
          type="button"
          role="tab"
          class="mem-tab"
          :class="{ 'mem-tab-active': activeTab === 'graph' }"
          @click="activeTab = 'graph'; handleTabChange('graph')"
        >
          <icon-share-alt class="mem-tab-ico" />
          图谱
          <span v-if="activeTab === 'graph'" class="mem-tab-underline" aria-hidden="true"></span>
        </button>
        <button
          type="button"
          role="tab"
          class="mem-tab"
          :class="{ 'mem-tab-active': activeTab === 'digest' }"
          @click="activeTab = 'digest'; handleTabChange('digest')"
        >
          <icon-file class="mem-tab-ico" />
          摘要 Digest
          <span v-if="activeTab === 'digest'" class="mem-tab-underline" aria-hidden="true"></span>
        </button>
        <button
          type="button"
          role="tab"
          class="mem-tab"
          :class="{ 'mem-tab-active': activeTab === 'skills' }"
          @click="activeTab = 'skills'; handleTabChange('skills')"
        >
          <icon-bulb class="mem-tab-ico" />
          技能
          <span v-if="activeTab === 'skills'" class="mem-tab-underline" aria-hidden="true"></span>
        </button>
      </div>

      <!-- ===== 图谱 Tab ===== -->
      <section v-if="activeTab === 'graph'" class="mem-panel">
        <!-- 聚类选择（胶囊 chips） -->
        <div class="mem-cluster-block">
          <div class="flex flex-wrap items-center justify-between gap-2">
            <div>
              <p class="text-sm font-medium text-text">主题聚类</p>
              <p class="mt-1 text-xs text-muted">选择一个聚类，查看其记忆子图</p>
            </div>
            <span class="mem-total-chip" v-if="!graphLoading">
              <icon-storage class="mem-total-ico" />
              共 {{ totalNodeCount }} 条记忆
            </span>
          </div>
          <div class="mt-3 flex flex-wrap items-center gap-2" role="group" aria-label="选择主题聚类">
            <a-spin :loading="graphLoading" class="mem-cluster-spin">
              <template v-if="clusterChips.length > 0">
                <button
                  v-for="chip in clusterChips"
                  :key="chip.type"
                  type="button"
                  class="mem-chip"
                  :class="{ 'mem-chip-active': selectedClusterType === chip.type }"
                  @click="handleSelectCluster(chip.type)"
                >
                  {{ chip.label }}
                  <span class="mem-chip-count">{{ chip.count }}</span>
                </button>
              </template>
              <p v-else class="mem-cluster-empty">暂无记忆数据，与 AI 对话后会自动沉淀长期记忆。</p>
            </a-spin>
          </div>
        </div>

        <!-- 图谱 + 详情联动 -->
        <div class="mt-6 grid grid-cols-1 gap-6 xl:grid-cols-3">
          <!-- 图谱卡片（占 2/3） -->
          <div class="mem-graph-card xl:col-span-2">
            <div class="flex items-center justify-between gap-3">
              <div>
                <h2 class="mem-serif-title text-xl font-bold tracking-tight">记忆图谱</h2>
                <p class="mt-1 text-sm text-muted">
                  {{ selectedClusterType ? `${clusterChips.find((c) => c.type === selectedClusterType)?.label || selectedClusterType} · 记忆关联图谱` : '选择一个聚类查看力导向子图' }}
                </p>
              </div>
              <span v-if="subgraph?.truncated" class="mem-badge mem-badge-warn">
                <icon-exclamation-circle class="mem-badge-ico" />
                {{ t('memory.graph.truncated') }}
              </span>
            </div>

            <!-- 未选择聚类 → 空提示；已选择 → 真实力导向图 -->
            <div v-if="!selectedClusterType" class="mem-graph-hint">
              <span class="mem-graph-hint-ico"><icon-branch /></span>
              <p class="mt-3 text-sm font-medium text-text-2">{{ t('memory.graph.selectClusterHint') }}</p>
              <p class="mt-1 text-xs text-muted">图谱按主题聚类组织，点击上方分类查看关联记忆</p>
            </div>
            <MemoryGraphView
              v-else
              :subgraph="subgraph"
              :loading="subgraphLoading"
              data-test="graph-view"
              @select-node="handleSelectNode"
            />

            <!-- 图例 -->
            <div class="mem-legend">
              <span class="flex items-center gap-2">
                <span class="mem-legend-dot mem-legend-core"></span>聚类主题
              </span>
              <span class="flex items-center gap-2">
                <span class="mem-legend-dot mem-legend-node"></span>关联记忆
              </span>
              <span class="flex items-center gap-2">
                <span class="mem-legend-line"></span>连线 · 关联强度
              </span>
            </div>
          </div>

          <!-- 详情面板（占 1/3） -->
          <div class="mem-detail-card">
            <MemoryNodeDetail
              :detail="nodeDetail"
              :loading="detailLoading"
              data-test="node-detail"
              :decay-saving="decaySaving"
              @edit="handleEdit"
              @soft-delete="handleSoftDelete"
              @hard-delete="handleHardDelete"
              @decay="handleDecaySave"
              @select-related="handleSelectRelated"
            />
          </div>
        </div>
      </section>

      <!-- ===== 摘要 Digest Tab ===== -->
      <section v-else-if="activeTab === 'digest'" class="mem-panel">
        <article class="mem-card mem-digest-card">
          <div class="flex flex-wrap items-start justify-between gap-3">
            <div>
              <h2 class="mem-serif-title text-xl font-bold tracking-tight">记忆摘要</h2>
              <p class="mt-1 text-sm text-muted">AI 依据长期记忆自动生成的偏好概览</p>
            </div>
            <span v-if="digestCached" class="mem-badge mem-badge-soft">
              <icon-storage class="mem-badge-ico" />
              缓存
            </span>
          </div>
          <a-spin :loading="digestLoading" class="block">
            <div
              v-if="digestText"
              class="mem-digest-text markdown-body"
              @click="handleDigestClick"
              v-html="digestHtml"
            ></div>
            <div v-else class="py-12 text-center text-muted">
              <icon-file class="mem-empty-ico" />
              <p class="mt-3">{{ t('memory.graph.digestEmpty') }}</p>
            </div>
          </a-spin>
        </article>
      </section>

      <!-- ===== 技能 Tab ===== -->
      <section v-else class="mem-panel">
        <a-spin :loading="skillsLoading" class="block">
          <div v-if="!skillsLoading && skills.length === 0" class="flex flex-col items-center justify-center py-20 text-muted">
            <icon-bulb class="mem-empty-ico" />
            <p class="mt-3">{{ t('memory.graph.skillsEmpty') }}</p>
          </div>
          <div v-else class="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            <article v-for="skill in skills" :key="skill.skill_id || skill.name" class="mem-skill-card">
              <div class="flex items-start justify-between gap-2">
                <h3 class="mem-skill-name">{{ skill.name }}</h3>
                <span class="mem-pill" :class="skillStatusCls(skill.status)">{{ skillStatusLabel(skill.status) }}</span>
              </div>
              <p v-if="skill.description" class="mem-skill-desc">{{ skill.description }}</p>
              <div class="mem-skill-meta">
                <span v-if="skill.maturity !== undefined">成熟度 {{ (skill.maturity * 100).toFixed(0) }}%</span>
                <span v-if="skill.use_count !== undefined">使用 {{ skill.use_count }} 次</span>
                <span v-if="skill.last_updated_at">更新于 {{ formatTime(skill.last_updated_at) }}</span>
              </div>
            </article>
          </div>
        </a-spin>
      </section>

      <!-- ===== 编辑弹窗 ===== -->
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

      <!-- 软删确认（进入回收站 + 选择留存天数） -->
      <RecycleBinDeleteModal
        :visible="softDeleteModalVisible"
        :title="t('memory.graph.softDeleteBtn')"
        :resource-name="nodeDetail?.content"
        :loading="softDeleteSaving"
        :hint="t('userRecycleBin.deleteHint')"
        @update:visible="(v) => !v && (softDeleteModalVisible = false)"
        @confirm="confirmSoftDelete"
      />
    </div>
  </div>
</template>

<style scoped>
/* ============================================================
   记忆空间 · 粉色翻新（对齐 yuxin-barbie-redesign/pages/memory.html）
   全部走 aicss 变量；主按钮粉渐变；卡片浅粉底粉边框
   ============================================================ */
.mem-page {
  height: 100%;
  background: var(--aicss-bg);
}
.mem-page::-webkit-scrollbar {
  width: 6px;
}
.mem-page::-webkit-scrollbar-thumb {
  border-radius: 999px;
  background: var(--aicss-border-strong);
}
.mem-page::-webkit-scrollbar-track {
  background: transparent;
}

/* 衬线标题 */
.mem-title,
.mem-serif-title {
  color: var(--aicss-text);
  font-family: var(--aicss-font-serif, Georgia, 'Songti SC', serif);
  letter-spacing: -0.01em;
}
.mem-title {
  line-height: 1.15;
}

/* ---- 通用自绘按钮（kb-btn 族） ---- */
.kb-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  height: 40px;
  padding: 0 18px;
  border: 1px solid transparent;
  border-radius: var(--aicss-radius);
  font-size: 13px;
  font-weight: 500;
  font-family: inherit;
  line-height: 1;
  cursor: pointer;
  white-space: nowrap;
  transition:
    opacity 0.2s ease,
    background 0.2s ease,
    border-color 0.2s ease,
    color 0.2s ease,
    transform 0.2s ease,
    box-shadow 0.2s ease;
}
.kb-btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}
.kb-btn-ico {
  font-size: 15px;
}
.kb-btn svg,
.kb-btn :deep(svg) {
  width: 15px;
  height: 15px;
}
.kb-btn-primary {
  background: linear-gradient(135deg, var(--aicss-accent) 0%, #ff5c8d 100%);
  color: #fff;
  box-shadow: var(--aicss-shadow-card);
}
.kb-btn-primary:hover:not(:disabled) {
  opacity: 0.92;
  transform: translateY(-1px);
  box-shadow: var(--aicss-shadow-elevated);
}
.kb-btn-primary:active:not(:disabled) {
  transform: translateY(0);
}
.kb-btn-ghost {
  border-color: var(--aicss-border);
  background: var(--aicss-surface);
  color: var(--aicss-text);
}
.kb-btn-ghost:hover:not(:disabled) {
  border-color: var(--aicss-border-strong);
  background: var(--aicss-bg-subtle);
}
.kb-btn.is-loading {
  opacity: 0.7;
  cursor: progress;
}

/* ---- Tab 栏（下划线式） ---- */
.mem-tabs {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 4px;
  margin-top: 28px;
  border-bottom: 1px solid var(--aicss-border);
}
.mem-tab {
  position: relative;
  display: inline-flex;
  align-items: center;
  gap: 7px;
  height: 44px;
  padding: 0 16px;
  border: none;
  background: transparent;
  color: var(--aicss-muted);
  font-size: 14px;
  font-weight: 500;
  font-family: inherit;
  cursor: pointer;
  transition:
    color 0.2s ease,
    background 0.2s ease;
}
.mem-tab:hover {
  background: var(--aicss-surface-2);
  color: var(--aicss-text);
  border-radius: var(--aicss-radius-sm) var(--aicss-radius-sm) 0 0;
}
.mem-tab-active {
  color: var(--aicss-accent-text);
}
.mem-tab-ico {
  font-size: 15px;
}
.mem-tab-underline {
  position: absolute;
  inset: auto 12px -1px;
  height: 2.5px;
  border-radius: 999px;
  background: linear-gradient(90deg, var(--aicss-accent), #ff5c8d);
}

/* ---- 面板间距 ---- */
.mem-panel {
  margin-top: 28px;
  padding-bottom: 40px;
}

/* ---- 聚类选择 ---- */
.mem-cluster-block {
  padding: 20px 22px;
  border: 1px solid var(--aicss-border);
  border-radius: var(--aicss-radius);
  background: var(--aicss-surface);
  box-shadow: var(--aicss-shadow-card);
}
.mem-total-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 5px 13px;
  border-radius: 999px;
  border: 1px solid color-mix(in srgb, var(--aicss-accent) 22%, var(--aicss-border));
  background: var(--aicss-accent-soft);
  color: var(--aicss-accent-text);
  font-size: 12px;
  font-weight: 600;
  white-space: nowrap;
}
.mem-total-ico {
  color: var(--aicss-accent);
}
.mem-cluster-spin {
  display: block;
  min-width: 100%;
}
.mem-chip {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  padding: 7px 15px;
  border: 1px solid var(--aicss-border);
  border-radius: 999px;
  background: var(--aicss-surface-2);
  color: var(--aicss-text-2);
  font-size: 13px;
  font-weight: 500;
  font-family: inherit;
  line-height: 1;
  cursor: pointer;
  transition:
    border-color 0.2s ease,
    background 0.2s ease,
    color 0.2s ease,
    box-shadow 0.2s ease;
}
.mem-chip:hover {
  border-color: var(--aicss-border-strong);
  background: var(--aicss-bg-subtle);
}
.mem-chip-active {
  border-color: var(--aicss-accent);
  background: linear-gradient(135deg, var(--aicss-accent) 0%, #ff5c8d 100%);
  color: #fff;
  box-shadow: var(--aicss-shadow-card);
}
.mem-chip-count {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 19px;
  height: 19px;
  padding: 0 6px;
  border-radius: 999px;
  background: color-mix(in srgb, var(--aicss-accent) 12%, transparent);
  color: var(--aicss-accent-text);
  font-size: 11px;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
}
.mem-chip-active .mem-chip-count {
  background: rgba(255, 255, 255, 0.24);
  color: #fff;
}
.mem-cluster-empty {
  margin: 0;
  padding: 6px 0;
  color: var(--aicss-muted);
  font-size: 13px;
}

/* ---- 图谱卡片 ---- */
.mem-graph-card {
  position: relative;
  display: flex;
  flex-direction: column;
  padding: 22px 24px;
  border: 1px solid var(--aicss-border);
  border-radius: var(--aicss-radius);
  background: var(--aicss-surface);
  box-shadow: var(--aicss-shadow-card);
}
.mem-graph-card :deep(.graph-shell) {
  margin-top: 18px;
  height: 440px;
  flex: none;
  border-color: var(--aicss-border);
  border-radius: var(--aicss-radius);
  background: var(--aicss-bg-subtle);
}
.mem-graph-hint {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  margin-top: 18px;
  flex: 1;
  min-height: 380px;
  border: 1px dashed var(--aicss-border-strong);
  border-radius: var(--aicss-radius);
  background: var(--aicss-bg-subtle);
}
.mem-graph-hint-ico {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 68px;
  height: 68px;
  border-radius: 50%;
  background: var(--aicss-accent-soft);
  color: var(--aicss-accent);
  font-size: 30px;
}
.mem-graph-hint-ico :deep(svg) {
  width: 30px;
  height: 30px;
}

/* 图例 */
.mem-legend {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: center;
  gap: 20px;
  margin-top: 16px;
  padding-top: 14px;
  border-top: 1px solid var(--aicss-border);
  color: var(--aicss-muted);
  font-size: 12px;
}
.mem-legend-dot {
  width: 12px;
  height: 12px;
  border-radius: 50%;
}
.mem-legend-core {
  background: linear-gradient(135deg, var(--aicss-accent), #ff9ec5);
}
.mem-legend-node {
  background: var(--aicss-surface-2);
  border: 1.5px solid var(--aicss-accent);
}
.mem-legend-line {
  width: 24px;
  height: 2px;
  border-radius: 999px;
  background: var(--aicss-accent);
  opacity: 0.55;
}

/* ---- 详情卡片 ---- */
.mem-detail-card {
  border: 1px solid var(--aicss-border);
  border-radius: var(--aicss-radius);
  background: var(--aicss-surface);
  box-shadow: var(--aicss-shadow-card);
}
.mem-detail-card :deep(.detail-shell) {
  height: 100%;
  min-height: 100%;
  border: none;
  border-radius: 0;
  background: transparent;
}

/* ---- 通用卡片 / 徽章 / 空态 ---- */
.mem-card {
  padding: 20px 22px;
  border: 1px solid var(--aicss-border);
  border-radius: var(--aicss-radius);
  background: var(--aicss-surface);
  box-shadow: var(--aicss-shadow-card);
}
.mem-badge {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 4px 11px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 500;
  white-space: nowrap;
}
.mem-badge-ico {
  font-size: 13px;
}
.mem-badge-soft {
  background: var(--aicss-surface-2);
  color: var(--aicss-muted);
}
.mem-badge-warn {
  background: rgba(230, 162, 60, 0.14);
  color: #b3741a;
}
.mem-empty-ico {
  display: block;
  margin: 0 auto;
  color: var(--aicss-subtle);
  font-size: 42px;
}

/* ---- Digest ---- */
.mem-digest-card {
  padding: 24px 26px;
}

/* 摘要 markdown 正文（复用 github-markdown-css，覆盖为粉色主题） */
.mem-digest-text {
  margin-top: 18px;
  font-size: 14px;
  line-height: 1.9;
}
.mem-digest-text :deep(h1),
.mem-digest-text :deep(h2),
.mem-digest-text :deep(h3),
.mem-digest-text :deep(h4) {
  color: var(--aicss-text);
  font-family: var(--aicss-font-serif, Georgia, 'Songti SC', serif);
  letter-spacing: -0.01em;
  margin-top: 22px;
  margin-bottom: 10px;
  padding-bottom: 6px;
  border-bottom: 1px solid var(--aicss-border);
  font-weight: 700;
}
.mem-digest-text :deep(h1:first-child),
.mem-digest-text :deep(h2:first-child),
.mem-digest-text :deep(h3:first-child) {
  margin-top: 2px;
}
.mem-digest-text :deep(p) {
  color: var(--aicss-text-2);
  line-height: 1.9;
  margin: 8px 0;
}
.mem-digest-text :deep(strong) {
  color: var(--aicss-text);
  font-weight: 600;
}
.mem-digest-text :deep(a) {
  color: var(--aicss-accent-text);
}
.mem-digest-text :deep(ul),
.mem-digest-text :deep(ol) {
  color: var(--aicss-text-2);
  padding-left: 1.6em;
  margin: 8px 0;
}
.mem-digest-text :deep(li) {
  line-height: 1.9;
  margin: 3px 0;
}
.mem-digest-text :deep(li::marker) {
  color: var(--aicss-accent);
}
.mem-digest-text :deep(blockquote) {
  margin: 10px 0;
  padding: 6px 14px;
  border-left: 3px solid color-mix(in srgb, var(--aicss-accent) 55%, transparent);
  background: var(--aicss-accent-soft);
  border-radius: 0 var(--aicss-radius-sm) var(--aicss-radius-sm) 0;
  color: var(--aicss-text-2);
}
.mem-digest-text :deep(blockquote p) {
  margin: 2px 0;
}
.mem-digest-text :deep(hr) {
  height: 1px;
  border: none;
  background: var(--aicss-border);
  margin: 18px 0;
}
.mem-digest-text :deep(code) {
  padding: 2px 6px;
  border-radius: 5px;
  background: var(--aicss-surface-2);
  color: var(--aicss-accent-text);
  font-size: 13px;
  font-family: var(--aicss-font-mono, ui-monospace, monospace);
}
.mem-digest-text :deep(.md-code-block) {
  margin: 12px 0;
  border: 1px solid var(--aicss-border);
  border-radius: var(--aicss-radius-sm);
  overflow: hidden;
  background: var(--aicss-bg-subtle);
}
.mem-digest-text :deep(.md-code-header) {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 6px 12px;
  background: var(--aicss-surface-2);
  border-bottom: 1px solid var(--aicss-border);
  font-size: 12px;
}
.mem-digest-text :deep(.md-code-lang) {
  color: var(--aicss-muted);
}
.mem-digest-text :deep(.md-code-copy-btn) {
  border: none;
  background: transparent;
  color: var(--aicss-accent-text);
  font-size: 12px;
  cursor: pointer;
}
.mem-digest-text :deep(.md-code-block pre) {
  margin: 0;
  padding: 12px 14px;
  background: transparent;
}
.mem-digest-text :deep(.md-code-block pre code) {
  background: transparent;
  padding: 0;
  color: var(--aicss-text-2);
}
.mem-digest-text :deep(table) {
  border-collapse: collapse;
  margin: 12px 0;
  width: 100%;
  font-size: 13px;
}
.mem-digest-text :deep(th),
.mem-digest-text :deep(td) {
  border: 1px solid var(--aicss-border);
  padding: 8px 12px;
  text-align: left;
}
.mem-digest-text :deep(th) {
  background: var(--aicss-surface-2);
  color: var(--aicss-text);
  font-weight: 600;
}

/* ---- 技能卡片 ---- */
.mem-skill-card {
  padding: 18px 20px;
  border: 1px solid var(--aicss-border);
  border-radius: var(--aicss-radius);
  background: var(--aicss-surface);
  box-shadow: var(--aicss-shadow-card);
  transition:
    transform 0.2s ease,
    box-shadow 0.2s ease,
    border-color 0.2s ease;
}
.mem-skill-card:hover {
  transform: translateY(-2px);
  border-color: color-mix(in srgb, var(--aicss-accent) 30%, var(--aicss-border));
  box-shadow: var(--aicss-shadow-elevated);
}
.mem-skill-name {
  margin: 0;
  font-size: 15px;
  font-weight: 600;
  color: var(--aicss-text);
}
.mem-skill-desc {
  margin: 10px 0 0;
  font-size: 13px;
  line-height: 1.7;
  color: var(--aicss-muted);
}
.mem-skill-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 14px;
  margin-top: 14px;
  padding-top: 12px;
  border-top: 1px dashed var(--aicss-border);
  color: var(--aicss-muted);
  font-size: 12px;
}
.mem-pill {
  display: inline-flex;
  align-items: center;
  padding: 3px 10px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 600;
  white-space: nowrap;
}
.st-active {
  background: var(--aicss-accent-soft);
  color: var(--aicss-accent-text);
}
.st-emerging {
  background: var(--aicss-surface-2);
  color: var(--aicss-text-2);
}
.st-candidate {
  background: rgba(230, 162, 60, 0.14);
  color: #b3741a;
}
.st-stale {
  background: var(--aicss-bg-subtle);
  color: var(--aicss-muted);
}
.st-deprecated {
  background: rgba(245, 63, 63, 0.1);
  color: #cf2525;
}

/* ---- 移动端 ---- */
@media (max-width: 640px) {
  .mem-cluster-block {
    padding: 16px 16px;
  }
  .mem-graph-card,
  .mem-detail-card {
    padding: 16px;
  }
  .mem-title {
    font-size: 26px;
  }
  .mem-tabs {
    margin-top: 20px;
  }
  .mem-tab {
    height: 40px;
    padding: 0 12px;
    font-size: 13px;
  }
}
</style>
