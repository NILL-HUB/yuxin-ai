<script setup lang="ts">
/**
 * 外部数据源管理弹窗（知识库页内嵌）
 *
 * 说明：后端外部数据源能力尚未落地，当前采用「原型模拟数据」先行把 UI 定稿。
 * 模拟列表见 mockSources；待后端 /external-data-sources 就绪后，
 * 仅需把 loadDataSources 替换为真实 service 调用（getExternalDataSources），
 * 并把列表项字段名与后端模型对齐即可，模板无需改动。
 */
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { Message } from '@arco-design/web-vue'
import { useI18n } from 'vue-i18n'
import { useCredentialStore } from '@/stores/credential'
import { AUTH_REQUIRED_EVENT } from '@/utils/request'
import { isCredentialLoggedIn } from '@/utils/auth'
import { useRoute } from 'vue-router'

const props = defineProps<{
  visible: boolean
}>()
const emit = defineEmits<{
  (e: 'update:visible', value: boolean): void
}>()

const route = useRoute()
const credentialStore = useCredentialStore()
const { t } = useI18n()
const isLoggedIn = computed(() => isCredentialLoggedIn(credentialStore.credential))

/* ============================================================
   模拟数据源定义（后端就绪后替换为真实接口返回）
   ============================================================ */
type SourceType = 'lark' | 'notion' | 'github' | 'drive' | 'enterprise_knowledge'

interface MockSource {
  id: string
  source_type: SourceType
  source_name: string
  authorization_status: 'granted' | 'pending' | 'revoked' | 'expired'
  sync_status: 'idle' | 'syncing' | 'success' | 'failed'
  last_synced_at: string | null
}

const MOCK_SOURCES: MockSource[] = [
  {
    id: 'mock-lark-01',
    source_type: 'lark',
    source_name: '产品研发知识库',
    authorization_status: 'granted',
    sync_status: 'success',
    last_synced_at: '2026-09-03T09:30:00',
  },
  {
    id: 'mock-notion-01',
    source_type: 'notion',
    source_name: 'Notion 团队空间',
    authorization_status: 'pending',
    sync_status: 'idle',
    last_synced_at: null,
  },
]

/* ============================================================
   状态
   ============================================================ */
const dataSources = ref<MockSource[]>([])
const loading = ref(false)
const syncingIds = ref<Record<string, boolean>>({})

// 解绑确认目标（自绘二次确认条）
const unbindTarget = ref<MockSource | null>(null)

// 新建表单（内联展开，不嵌套弹窗，避免 Arco 多层 modal wrapper 残留）
const creating = ref(false)
const expandCreate = ref(false)
const createForm = ref({
  source_type: 'lark' as SourceType,
  source_name: '',
  config: {} as Record<string, string>,
})

const sourceTypeOptions: Array<{ value: SourceType; label: string }> = [
  { value: 'lark', label: t('externalDataSource.lark') },
  { value: 'notion', label: t('externalDataSource.notion') },
  { value: 'github', label: t('externalDataSource.github') },
  { value: 'drive', label: t('externalDataSource.drive') },
  { value: 'enterprise_knowledge', label: t('externalDataSource.enterpriseKnowledge') },
]

/* 各类型表单字段（原型字段定义） */
const credentialFields = computed(() => {
  switch (createForm.value.source_type) {
    case 'lark':
      return [
        { key: 'app_id', label: t('externalDataSource.fields.appId'), required: true, full: false },
        { key: 'app_secret', label: t('externalDataSource.fields.appSecret'), required: true, full: false },
        { key: 'folder_token', label: t('externalDataSource.fields.folderToken'), required: false, full: true },
      ]
    case 'notion':
      return [
        { key: 'integration_token', label: t('externalDataSource.fields.integrationToken'), required: true, full: true },
        { key: 'database_id', label: t('externalDataSource.fields.databaseId'), required: false, full: false },
        { key: 'page_id', label: t('externalDataSource.fields.pageId'), required: false, full: false },
      ]
    case 'github':
      return [
        { key: 'personal_access_token', label: t('externalDataSource.fields.personalAccessToken'), required: true, full: true },
        { key: 'owner', label: t('externalDataSource.fields.owner'), required: true, full: false },
        { key: 'repo', label: t('externalDataSource.fields.repo'), required: true, full: false },
      ]
    case 'drive':
      return [
        { key: 'folder_path', label: t('externalDataSource.fields.folderPath'), required: false, full: false },
      ]
    case 'enterprise_knowledge':
      return [
        { key: 'endpoint', label: t('externalDataSource.fields.endpoint'), required: false, full: false },
        { key: 'api_key', label: t('externalDataSource.fields.apiKey'), required: false, full: false },
      ]
    default:
      return []
  }
})

/* ============================================================
   加载：后端就绪后替换为 getExternalDataSources() 真实调用
   ============================================================ */
const loadDataSources = async () => {
  loading.value = true
  try {
    // TODO(后端接入): const res = await getExternalDataSources(); dataSources.value = res.data || []
    await new Promise((resolve) => setTimeout(resolve, 400))
    dataSources.value = MOCK_SOURCES.map((s) => ({ ...s }))
  } finally {
    loading.value = false
  }
}

const resetCreateForm = () => {
  createForm.value = {
    source_type: 'lark',
    source_name: '',
    config: {},
  }
}

/* 模拟「绑定成功」：把新数据源插入列表顶部并收起表单 */
const handleCreate = async () => {
  if (!createForm.value.source_name.trim()) {
    Message.error(t('externalDataSource.createFailed'))
    return
  }
  creating.value = true
  try {
    // TODO(后端接入): await createExternalDataSource({...})
    await new Promise((resolve) => setTimeout(resolve, 500))
    dataSources.value.unshift({
      id: `mock-${Date.now()}`,
      source_type: createForm.value.source_type,
      source_name: createForm.value.source_name.trim(),
      authorization_status: 'pending',
      sync_status: 'idle',
      last_synced_at: null,
    })
    Message.success(t('externalDataSource.createSuccess'))
    expandCreate.value = false
    resetCreateForm()
  } finally {
    creating.value = false
  }
}

/* 模拟同步（表单态成功） */
const handleSync = async (record: MockSource) => {
  if (syncingIds.value[record.id]) return
  syncingIds.value[record.id] = true
  record.sync_status = 'syncing'
  try {
    await new Promise((resolve) => setTimeout(resolve, 900))
    record.sync_status = 'success'
    record.last_synced_at = new Date().toISOString()
    Message.success(
      t('externalDataSource.syncSuccess', {
        document: record.source_type === 'lark' ? 32 : 12,
        segment: record.source_type === 'lark' ? 186 : 74,
      }),
    )
  } finally {
    syncingIds.value[record.id] = false
  }
}

/* 解绑 */
const confirmUnbind = async () => {
  if (!unbindTarget.value) return
  const target = unbindTarget.value
  dataSources.value = dataSources.value.filter((s) => s.id !== target.id)
  Message.success(t('externalDataSource.delete'))
  unbindTarget.value = null
}

const openLoginModal = () => {
  if (typeof window === 'undefined') return
  window.dispatchEvent(
    new CustomEvent(AUTH_REQUIRED_EVENT, {
      detail: { redirect: route.fullPath },
    }),
  )
}

const closeModal = () => {
  expandCreate.value = false
  unbindTarget.value = null
  emit('update:visible', false)
}

/* ============================================================
   展示辅助
   ============================================================ */
const typeMeta: Record<SourceType, { labelKey: string; cls: string }> = {
  lark: { labelKey: 'lark', cls: 'type-lark' },
  notion: { labelKey: 'notion', cls: 'type-notion' },
  github: { labelKey: 'github', cls: 'type-github' },
  drive: { labelKey: 'drive', cls: 'type-drive' },
  enterprise_knowledge: { labelKey: 'enterpriseKnowledge', cls: 'type-enterprise' },
}

const sourceTypeLabel = (type: SourceType) => t(`externalDataSource.${typeMeta[type].labelKey}`)
const sourceTypeCls = (type: SourceType) => typeMeta[type]?.cls || 'type-drive'

const formatTime = (value: string | null) => {
  if (!value) return '-'
  const d = new Date(value)
  if (Number.isNaN(d.getTime())) return value
  const p = (n: number) => String(n).padStart(2, '0')
  return `${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`
}

const authLabel = (status: string) => t(`externalDataSource.${status}`)

// 打开时重置表单为默认「飞书」并展开配置表单（避免首次打开无表单的断层），随后加载列表
watch(
  () => props.visible,
  async (visible) => {
    if (visible && isLoggedIn.value) {
      resetCreateForm()
      expandCreate.value = true
      await loadDataSources()
    }
  },
)

watch(
  isLoggedIn,
  async (loggedIn) => {
    if (!loggedIn) {
      dataSources.value = []
      return
    }
    if (props.visible) {
      await loadDataSources()
    }
  },
  { immediate: true },
)

// 关闭时同步清理展开态
watch(
  () => props.visible,
  (v) => {
    if (!v) {
      expandCreate.value = false
      unbindTarget.value = null
    }
  },
)

onBeforeUnmount(() => {
  expandCreate.value = false
  unbindTarget.value = null
})
</script>

<template>
  <a-modal
    :visible="visible"
    :footer="false"
    hide-title
    :closable="false"
    :width="680"
    :mask-closable="true"
    :unmount-on-close="true"
    modal-class="external-source-modal"
    @cancel="closeModal"
  >
    <!-- 弹窗头：完全自绘（复刻原型 px-6 py-5 / gap-3 结构，避免 Arco header 定位干扰） -->
    <div class="eds-m-head">
      <div class="eds-m-head-main">
        <span class="eds-header-mark"><icon-cloud class="eds-header-icon" /></span>
        <div class="eds-header-text">
          <h3 class="eds-title">{{ t('externalDataSource.title') }}</h3>
          <p class="eds-subtitle">绑定飞书、Notion、GitHub 等外部数据，供知识库检索使用</p>
        </div>
      </div>
      <button type="button" class="eds-m-close" aria-label="关闭" @click="closeModal">
        <icon-close />
      </button>
    </div>

    <!-- 未登录态 -->
    <div v-if="!isLoggedIn" class="eds-login-required">
      <div class="eds-login-ico"><icon-user /></div>
      <h4 class="eds-login-title">{{ t('externalDataSource.loginRequiredTitle') }}</h4>
      <p class="eds-login-desc">{{ t('externalDataSource.loginRequiredDescription') }}</p>
      <button type="button" class="kb-btn kb-btn-primary" @click="openLoginModal">
        {{ t('common.actions.login') }}
      </button>
    </div>

    <!-- 已登录 -->
    <div v-else class="eds-body">
      <div v-if="loading" class="eds-loading">
        <icon-loading class="eds-loading-spin" />
        <span>加载中…</span>
      </div>

      <template v-else>
        <!-- 已绑定列表（含空态） -->
        <div v-if="dataSources.length === 0" class="eds-empty">
          <span class="eds-empty-ico"><icon-storage /></span>
          <p>{{ t('externalDataSource.noData') }}</p>
          <p class="eds-empty-hint">绑定飞书、Notion、GitHub 等外部数据，供知识库检索使用</p>
        </div>

        <template v-else>
          <!-- 标题行 -->
          <div class="eds-section-head">
            <h4 class="eds-section-title">已绑定数据源</h4>
            <span class="eds-count-chip">{{ dataSources.length }} 个已绑定</span>
          </div>

          <!-- 列表卡片 -->
          <div class="eds-list">
            <div v-for="source in dataSources" :key="source.id" class="eds-row">
              <!-- 图标块：按数据源类型的品牌配色 -->
              <span class="eds-source-ico" :class="sourceTypeCls(source.source_type)">
                <icon-send v-if="source.source_type === 'lark'" />
                <icon-file v-else-if="source.source_type === 'notion'" />
                <icon-github v-else-if="source.source_type === 'github'" />
                <icon-folder v-else-if="source.source_type === 'drive'" />
                <icon-common v-else />
              </span>

              <!-- 名称 + 徽章 + 副行 -->
              <div class="eds-row-main">
                <div class="eds-row-title-line">
                  <p class="eds-row-name">{{ source.source_name }}</p>
                  <span
                    class="eds-badge"
                    :class="source.authorization_status === 'granted' ? 'badge-ok' : 'badge-wait'"
                  >
                    <icon-check v-if="source.authorization_status === 'granted'" class="eds-badge-ico" />
                    <icon-clock-circle v-else class="eds-badge-ico" />
                    {{ authLabel(source.authorization_status) }}
                  </span>
                </div>
                <p class="eds-row-sub">
                  {{ sourceTypeLabel(source.source_type) }}
                  <template v-if="source.last_synced_at"> · 同步于 {{ formatTime(source.last_synced_at) }}</template>
                  <template v-else> · 需要补充授权后开始同步</template>
                </p>
              </div>

              <!-- 操作按钮组 -->
              <div class="eds-row-actions">
                <template v-if="source.authorization_status === 'pending'">
                  <button
                    type="button"
                    class="kb-btn kb-btn-primary kb-btn-sm"
                    @click="source.authorization_status = 'granted'"
                  >
                    <icon-safe class="kb-btn-ico" />去授权
                  </button>
                </template>
                <template v-else>
                  <button
                    type="button"
                    class="kb-btn kb-btn-ghost kb-btn-sm"
                    :disabled="syncingIds[source.id]"
                    @click="handleSync(source)"
                  >
                    <icon-sync class="kb-btn-ico" />同步
                  </button>
                </template>
                <button type="button" class="eds-unlink-btn" aria-label="解绑" @click="unbindTarget = source">
                  <icon-link />
                </button>
              </div>
            </div>
          </div>
        </template>

        <!-- 解绑确认条 -->
        <div v-if="unbindTarget" class="eds-unbind-bar">
          <div class="eds-unbind-text">
            <icon-exclamation-circle class="eds-unbind-ico" />
            <span>确认解绑「{{ unbindTarget.source_name }}」？解绑后该数据源将不再同步，且无法恢复。</span>
          </div>
          <div class="eds-unbind-actions">
            <button type="button" class="kb-btn kb-btn-ghost kb-btn-sm" @click="unbindTarget = null">取消</button>
            <button type="button" class="kb-btn kb-btn-danger kb-btn-sm" @click="confirmUnbind">确认解绑</button>
          </div>
        </div>
      </template>

      <!-- ===== 绑定新数据源 ===== -->
      <div class="eds-create">
        <div class="eds-create-head">
          <h4 class="eds-section-title">绑定新数据源</h4>
          <span class="eds-create-note">数据仅用于知识库检索与同步</span>
        </div>

        <!-- 类型 chips -->
        <div class="eds-chips">
          <button
            v-for="option in sourceTypeOptions"
            :key="option.value"
            type="button"
            class="eds-chip"
            :class="createForm.source_type === option.value ? 'chip-active' : ''"
            @click="
              createForm.source_type = option.value;
              createForm.config = {};
              expandCreate = true;
            "
          >
            <icon-send v-if="option.value === 'lark'" class="eds-chip-ico" />
            <icon-file v-else-if="option.value === 'notion'" class="eds-chip-ico" />
            <icon-github v-else-if="option.value === 'github'" class="eds-chip-ico" />
            <icon-folder v-else-if="option.value === 'drive'" class="eds-chip-ico" />
            <icon-common v-else class="eds-chip-ico" />
            {{ option.label }}
          </button>
        </div>

        <!-- 表单 -->
        <form v-if="expandCreate" class="eds-form" @submit.prevent="handleCreate">
          <div class="eds-field eds-field-full">
            <label class="eds-label" for="eds-source-name">
              数据源名称 <span class="eds-required">*</span>
            </label>
            <input
              id="eds-source-name"
              v-model="createForm.source_name"
              type="text"
              class="kb-input"
              :placeholder="'例如：' + (createForm.source_type === 'drive' ? '本地文档目录' : '产品知识库')"
            />
          </div>
          <div
            v-for="field in credentialFields"
            :key="field.key"
            class="eds-field"
            :class="field.full ? 'eds-field-full' : ''"
          >
            <label class="eds-label" :for="'eds-' + field.key">
              {{ field.label }}
              <span v-if="field.required" class="eds-required">*</span>
              <span v-else class="eds-optional">选填</span>
            </label>
            <input
              :id="'eds-' + field.key"
              v-model="createForm.config[field.key]"
              :type="field.key === 'app_secret' || field.key === 'integration_token' || field.key === 'api_key' ? 'password' : 'text'"
              class="kb-input"
              :placeholder="field.key === 'folder_token' ? '文件夹链接中的 token（不填默认同步有权限的全部文档）' : field.label"
            />
          </div>

          <div class="eds-secure-note">
            <icon-lock class="eds-secure-ico" />
            凭证仅保存在你的账号下，用于定时同步该数据源；可随时解绑。
          </div>

          <!-- 底部操作条 -->
          <div class="eds-form-actions">
            <button type="button" class="kb-btn kb-btn-ghost" @click="expandCreate = false">
              取消
            </button>
            <button type="submit" class="kb-btn kb-btn-primary" :class="{ 'is-loading': creating }" :disabled="creating">
              <icon-link v-if="!creating" class="kb-btn-ico" />
              {{ creating ? '绑定中…' : '绑定数据源' }}
            </button>
          </div>
        </form>
      </div>
    </div>
  </a-modal>
</template>

<style scoped>
/* ============================================================
   外部数据源弹窗 · 自绘主题样式（对齐 aicss 变量 / 原型 knowledge.html）
   不使用 Arco 原生控件视觉；全部控件走 --aicss-* / --tw-* 变量
   modal 外壳样式见文末非 scoped 块（modal 经 Teleport 渲染，scoped 无法命中）
   ============================================================ */

/* ---- 弹窗头（复刻原型 px-6 py-5 / items-start / gap-3） ---- */
.eds-m-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  padding: 12px 28px 22px;
  border-bottom: 1px solid var(--aicss-border);
}
.eds-m-head-main {
  display: flex;
  align-items: center;
  gap: 14px;
  min-width: 0;
}
.eds-header-mark {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 40px;
  height: 40px;
  flex-shrink: 0;
  border-radius: var(--aicss-radius);
  background: var(--aicss-surface-2);
  color: var(--aicss-accent);
}
.eds-header-icon {
  font-size: 20px;
}
.eds-header-text {
  min-width: 0;
}
.eds-title {
  margin: 0;
  font-family: var(--aicss-font-serif, Georgia, 'Songti SC', serif);
  font-size: 18px;
  font-weight: 600;
  line-height: 1.4;
  color: var(--aicss-text);
}
.eds-subtitle {
  margin: 6px 0 0;
  font-size: 12px;
  line-height: 1.5;
  color: var(--aicss-muted);
}
.eds-m-close {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  flex-shrink: 0;
  padding: 0;
  border: none;
  border-radius: var(--aicss-radius-sm);
  background: transparent;
  color: var(--aicss-muted);
  cursor: pointer;
  transition:
    background 0.2s ease,
    color 0.2s ease;
}
.eds-m-close:hover {
  background: var(--aicss-surface-2);
  color: var(--aicss-text);
}
.eds-m-close svg,
.eds-m-close :deep(svg) {
  width: 15px;
  height: 15px;
}

/* ---- 主体（复刻原型 px-6 py-5） ---- */
.eds-body {
  max-height: 68vh;
  overflow-y: auto;
  padding: 22px 28px 28px;
}

/* ---- 区块标题 ---- */
.eds-section-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.eds-section-title {
  margin: 0;
  font-size: 14px;
  font-weight: 600;
  color: var(--aicss-text);
}
.eds-count-chip {
  font-family: var(--aicss-font-mono, ui-monospace, monospace);
  font-size: 12px;
  color: var(--aicss-muted);
}

/* ---- 加载/空态 ---- */
.eds-loading {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 40px 0;
  color: var(--aicss-muted);
  font-size: 13px;
}
.eds-loading-spin {
  animation: eds-rotate 1s linear infinite;
}
@keyframes eds-rotate {
  to {
    transform: rotate(360deg);
  }
}
.eds-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 36px 0 40px;
  margin-top: 12px;
  border: 1px dashed var(--aicss-border-strong);
  border-radius: var(--aicss-radius);
  background: var(--aicss-bg-subtle);
  color: var(--aicss-muted);
  font-size: 13px;
}
.eds-empty-ico {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 52px;
  height: 52px;
  margin-bottom: 12px;
  border-radius: 50%;
  background: var(--aicss-surface-2);
  color: var(--aicss-accent);
  font-size: 24px;
}
.eds-empty p {
  margin: 0;
}
.eds-empty-hint {
  margin-top: 4px;
  font-size: 12px;
}

/* ---- 绑定列表行 ---- */
.eds-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
  margin-top: 16px;
}
.eds-row {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 16px;
  border: 1px solid var(--aicss-border);
  border-radius: var(--aicss-radius);
  background: var(--aicss-bg-subtle);
  transition: border-color 0.2s ease;
}
.eds-row:hover {
  border-color: color-mix(in srgb, var(--aicss-accent) 30%, var(--aicss-border));
}
.eds-source-ico {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 42px;
  height: 42px;
  flex-shrink: 0;
  border-radius: var(--aicss-radius-sm);
  color: #fff;
  font-size: 18px;
  box-shadow: var(--aicss-shadow-card);
}
.eds-source-ico svg,
.eds-source-ico :deep(svg) {
  width: 18px;
  height: 18px;
}
.type-lark {
  background: linear-gradient(135deg, #4fc3f7, #0288d1);
}
.type-notion {
  background: linear-gradient(135deg, #3b3b3b, #111111);
}
.type-github {
  background: linear-gradient(135deg, #6b7280, #1f2937);
}
.type-drive {
  background: linear-gradient(135deg, #81d4fa, #0288d1);
}
.type-enterprise {
  background: linear-gradient(135deg, var(--tw-accent, #ff9ec5), var(--aicss-accent));
}
.eds-row-main {
  min-width: 0;
  flex: 1;
}
.eds-row-title-line {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
}
.eds-row-name {
  margin: 0;
  font-size: 14px;
  font-weight: 600;
  color: var(--aicss-text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.eds-badge {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  padding: 2px 8px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 500;
  white-space: nowrap;
}
.badge-ok {
  background: color-mix(in srgb, var(--aicss-accent) 12%, transparent);
  color: var(--aicss-accent-text);
}
.badge-wait {
  background: var(--aicss-surface-2);
  color: var(--aicss-muted);
}
.eds-badge-ico {
  font-size: 12px;
}
.eds-row-sub {
  margin: 4px 0 0;
  font-size: 12px;
  color: var(--aicss-muted);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.eds-row-actions {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-shrink: 0;
}
/* 解绑（unlink）小图标按钮 */
.eds-unlink-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 30px;
  height: 30px;
  padding: 0;
  border: none;
  border-radius: var(--aicss-radius-sm);
  background: transparent;
  color: var(--aicss-muted);
  cursor: pointer;
  transition:
    background 0.2s ease,
    color 0.2s ease;
}
.eds-unlink-btn svg,
.eds-unlink-btn :deep(svg) {
  width: 15px;
  height: 15px;
}
.eds-unlink-btn:hover {
  background: var(--aicss-surface-2);
  color: #f53f3f;
}

/* ---- 解绑确认条 ---- */
.eds-unbind-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-top: 12px;
  padding: 10px 14px;
  border: 1px solid color-mix(in srgb, #f53f3f 30%, var(--aicss-border));
  border-radius: var(--aicss-radius);
  background: color-mix(in srgb, #f53f3f 6%, var(--aicss-surface));
}
.eds-unbind-text {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
  font-size: 12px;
  color: var(--aicss-text-2);
  line-height: 1.5;
}
.eds-unbind-ico {
  flex-shrink: 0;
  color: #f53f3f;
}
.eds-unbind-actions {
  display: flex;
  gap: 6px;
  flex-shrink: 0;
}

/* ---- 绑定新数据源（复刻原型 mt-6 + pt-5） ---- */
.eds-create {
  margin-top: 28px;
  padding-top: 24px;
  border-top: 1px solid var(--aicss-border);
}
.eds-create-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.eds-create-note {
  font-size: 12px;
  color: var(--aicss-muted);
}

/* 类型 chips（复刻原型 mt-3） */
.eds-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin-top: 16px;
}
.eds-chip {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  padding: 8px 15px;
  border: 1px solid var(--aicss-border);
  border-radius: var(--aicss-radius-sm);
  background: var(--aicss-surface);
  font-size: 13px;
  font-weight: 500;
  line-height: 1;
  color: var(--aicss-text);
  cursor: pointer;
  transition:
    border-color 0.2s ease,
    background 0.2s ease,
    color 0.2s ease;
}
.eds-chip:hover {
  border-color: var(--aicss-border-strong);
  background: var(--aicss-bg-subtle);
}
.eds-chip.chip-active {
  border-color: var(--aicss-accent);
  background: var(--aicss-accent-soft);
  color: var(--aicss-accent-text);
}
.eds-chip-ico {
  font-size: 14px;
  color: currentColor;
}

/* 表单 */
.eds-form {
  display: flex;
  flex-wrap: wrap;
  gap: 14px;
  margin-top: 18px;
}
.eds-field {
  flex: 1 1 calc(50% - 6px);
  min-width: 220px;
}
.eds-field-full {
  flex-basis: 100%;
}
.eds-label {
  display: block;
  margin-bottom: 6px;
  font-size: 13px;
  font-weight: 500;
  color: var(--aicss-text);
}
.eds-required {
  color: #f53f3f;
}
.eds-optional {
  color: var(--aicss-muted);
  font-weight: 400;
}
.eds-secure-note {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-basis: 100%;
  padding: 8px 12px;
  border-radius: var(--aicss-radius-sm);
  background: var(--aicss-surface-2);
  font-size: 12px;
  color: var(--aicss-muted);
  line-height: 1.5;
}
.eds-secure-ico {
  flex-shrink: 0;
  color: var(--aicss-accent);
}
.eds-form-actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  flex-basis: 100%;
  margin-top: 4px;
}

/* ---- 未登录 ---- */
.eds-login-required {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 44px 20px 48px;
}
.eds-login-ico {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 72px;
  height: 72px;
  margin-bottom: 14px;
  border-radius: 50%;
  background: var(--aicss-surface-2);
  color: var(--aicss-muted);
  font-size: 32px;
}
.eds-login-title {
  margin: 0;
  font-size: 17px;
  font-weight: 600;
  color: var(--aicss-text);
}
.eds-login-desc {
  margin: 6px 0 18px;
  max-width: 320px;
  text-align: center;
  font-size: 13px;
  color: var(--aicss-muted);
  line-height: 1.6;
}

/* ---- 通用自绘按钮（与知识库列表页共用命名） ---- */
.kb-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  height: 38px;
  padding: 0 16px;
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
    transform 0.2s var(--aicss-ease, ease);
}
.kb-btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}
.kb-btn-sm {
  height: 32px;
  padding: 0 12px;
  font-size: 12px;
  border-radius: var(--aicss-radius-sm);
}
.kb-btn-ico {
  font-size: 14px;
}
.kb-btn-primary {
  background: linear-gradient(135deg, var(--aicss-accent) 0%, #ff5c8d 100%);
  color: #fff;
  box-shadow: var(--aicss-shadow-card);
}
.kb-btn-primary:hover:not(:disabled) {
  opacity: 0.92;
  transform: translateY(-1px);
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
.kb-btn-danger {
  background: linear-gradient(135deg, #f53f3f, #e02d2d);
  color: #fff;
}

/* ---- 自绘输入框 ---- */
.kb-input {
  width: 100%;
  height: 38px;
  padding: 0 13px;
  border: 1px solid var(--aicss-border);
  border-radius: var(--aicss-radius-sm);
  background: var(--aicss-bg-subtle);
  color: var(--aicss-text);
  font-size: 13px;
  font-family: inherit;
  outline: none;
  box-sizing: border-box;
  transition:
    border-color 0.2s ease,
    box-shadow 0.2s ease;
}
.kb-input::placeholder {
  color: var(--aicss-muted);
}
.kb-input:focus {
  border-color: var(--aicss-accent);
  box-shadow: 0 0 0 3px var(--aicss-accent-soft);
}
.kb-btn.is-loading {
  opacity: 0.7;
  cursor: progress;
}
</style>

<!-- ============================================================
     非 scoped：Arco Modal 经 Teleport 渲染到 body，scoped 选择器无法命中
     外壳。用 modal-class="external-source-modal" 精准限定，只影响本弹窗。
     ============================================================ -->
<style>
.external-source-modal {
  border-radius: var(--aicss-radius-lg);
  background: var(--aicss-surface);
  overflow: hidden;
}
.external-source-modal .arco-modal-content {
  padding: 0;
}
</style>
