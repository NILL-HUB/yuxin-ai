<script setup lang="ts">
import { onMounted, ref, computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { Message } from '@arco-design/web-vue'
import {
  listPublicAIFeatures,
  updatePublicAIFeature,
  listAvailableModels,
  type PublicAIFeature,
  type AvailableModel,
} from '@/services/admin-public-ai-feature'
import { getErrorMessage } from '@/utils/error'

const { t } = useI18n()

const loading = ref(false)
const features = ref<PublicAIFeature[]>([])
// allModels: 列表展示用的全量模型（用于 getModelLabel 显示友好名称）
// editModels: 编辑弹层下拉框用的按 model_type 过滤的模型
const allModels = ref<AvailableModel[]>([])
const editModels = ref<AvailableModel[]>([])
const editingKey = ref<string | null>(null)
const editingFeature = ref<PublicAIFeature | null>(null)
const saving = ref(false)
const editForm = ref({
  model_config_id: '',
  enabled: true,
  fallback_tier: 'cheap',
})

const categoryFilter = ref('')
const filteredFeatures = computed(() => {
  if (!categoryFilter.value) return features.value
  return features.value.filter(f => f.feature_category === categoryFilter.value)
})

const categories = [
  { value: '', label: t('admin.publicAIFeature.categories.all') },
  { value: 'icon', label: t('admin.publicAIFeature.categories.icon') },
  { value: 'memory', label: t('admin.publicAIFeature.categories.memory') },
  { value: 'routing', label: t('admin.publicAIFeature.categories.routing') },
  { value: 'assistant', label: t('admin.publicAIFeature.categories.assistant') },
  { value: 'conversation', label: t('admin.publicAIFeature.categories.conversation') },
  { value: 'general', label: t('admin.publicAIFeature.categories.general') },
]

const fallbackTiers = [
  { value: 'cheap', label: t('admin.publicAIFeature.tiers.cheap') },
  { value: 'standard', label: t('admin.publicAIFeature.tiers.standard') },
  { value: 'strong', label: t('admin.publicAIFeature.tiers.strong') },
]

function getModelLabel(modelId: string | null): string {
  if (!modelId) return ''
  const m = allModels.value.find(m => m.id === modelId)
  return m ? m.label : modelId
}

async function loadFeatures() {
  loading.value = true
  try {
    const res = await listPublicAIFeatures()
    features.value = res.items
  } catch (e) {
    Message.error(getErrorMessage(e, t('common.loadFailed')))
  } finally {
    loading.value = false
  }
}

async function loadAllModels() {
  try {
    const res = await listAvailableModels()
    allModels.value = res.items
  } catch (e) {
    Message.error(getErrorMessage(e, t('common.loadFailed')))
  }
}

async function loadEditModels(modelType?: string) {
  try {
    const res = await listAvailableModels(modelType)
    editModels.value = res.items
  } catch (e) {
    Message.error(getErrorMessage(e, t('common.loadFailed')))
  }
}

function startEdit(feature: PublicAIFeature) {
  editingFeature.value = feature
  editingKey.value = feature.feature_key
  editForm.value = {
    model_config_id: feature.model_config_id || '',
    enabled: feature.enabled,
    fallback_tier: feature.fallback_tier,
  }
  // 按功能的 model_type 加载对应类型的可选模型，防止误选不匹配的类型
  loadEditModels(feature.model_type)
}

async function saveFeature() {
  if (!editingKey.value) return
  saving.value = true
  try {
    await updatePublicAIFeature(editingKey.value, {
      model_config_id: editForm.value.model_config_id || undefined,
      enabled: editForm.value.enabled,
      fallback_tier: editForm.value.fallback_tier,
    })
    Message.success(t('common.saveSuccess'))
    editingFeature.value = null
    editingKey.value = null
    await loadFeatures()
  } catch (e) {
    Message.error(getErrorMessage(e, t('common.saveFailed')))
  } finally {
    saving.value = false
  }
}

function cancelEdit() {
  editingFeature.value = null
  editingKey.value = null
}

onMounted(() => {
  loadFeatures()
  loadAllModels()
})
</script>

<template>
  <div class="p-6">
    <div class="flex items-center justify-between mb-4">
      <h1 class="text-2xl font-bold">{{ t('admin.publicAIFeature.title') }}</h1>
      <select v-model="categoryFilter" class="border rounded px-3 py-2 text-sm">
        <option v-for="c in categories" :key="c.value" :value="c.value">{{ c.label }}</option>
      </select>
    </div>

    <p class="text-gray-600 mb-6 text-sm">{{ t('admin.publicAIFeature.description') }}</p>

    <div v-if="loading" class="text-center py-8 text-gray-500">{{ t('common.loading') }}</div>

    <div v-else class="space-y-3">
      <div v-for="feature in filteredFeatures" :key="feature.feature_key"
           class="border rounded-lg p-4 hover:shadow-sm transition-shadow">
        <div class="flex items-start justify-between">
          <div class="flex-1">
            <!-- 主标题：中文名 -->
            <div class="flex items-center gap-2 mb-1">
              <span class="font-medium text-base">{{ feature.feature_name }}</span>
              <span class="text-xs px-2 py-0.5 bg-gray-100 rounded">{{ t(`admin.publicAIFeature.categories.${feature.feature_category}`) }}</span>
              <span class="text-xs px-2 py-0.5 bg-blue-50 text-blue-600 rounded">{{ t(`admin.publicAIFeature.modelTypes.${feature.model_type}`) }}</span>
              <span v-if="feature.billable" class="text-xs px-2 py-0.5 bg-amber-50 text-amber-700 rounded">{{ t('admin.publicAIFeature.billable') }}</span>
              <span v-else class="text-xs px-2 py-0.5 bg-gray-100 text-gray-500 rounded">{{ t('admin.publicAIFeature.systemBorne') }}</span>
              <span v-if="feature.enabled" class="text-xs px-2 py-0.5 bg-green-100 text-green-700 rounded">{{ t('common.enabled') }}</span>
              <span v-else class="text-xs px-2 py-0.5 bg-red-100 text-red-700 rounded">{{ t('common.disabled') }}</span>
            </div>
            <!-- 说明描述 -->
            <div v-if="feature.feature_description" class="text-sm text-gray-600 mb-1">{{ feature.feature_description }}</div>
            <!-- 功能键灰色小字 + 绑定模型 -->
            <div class="flex items-center gap-4 text-sm text-gray-400 mt-1">
              <span class="font-mono text-xs">{{ feature.feature_key }}</span>
            </div>
            <div class="text-sm mt-2">
              <span class="text-gray-500">{{ t('admin.publicAIFeature.boundModel') }}:</span>
              <span v-if="feature.model_config_id" class="ml-2 text-gray-800">{{ getModelLabel(feature.model_config_id) }}</span>
              <span v-else class="ml-2 text-gray-400">{{ t('admin.publicAIFeature.unbound') }}（{{ t('admin.publicAIFeature.useFallback') }}: {{ feature.fallback_tier }}）</span>
            </div>
          </div>
          <button class="text-blue-600 hover:underline text-sm ml-4 shrink-0"
                  @click="startEdit(feature)">
            {{ t('common.edit') }}
          </button>
        </div>
      </div>
    </div>

    <!-- 编辑弹层 -->
    <div v-if="editingKey" class="fixed inset-0 bg-black bg-opacity-30 flex items-center justify-center z-50" @click.self="cancelEdit">
      <div class="bg-white rounded-lg p-6 w-[480px]">
        <h2 class="text-xl font-bold mb-4">{{ t('admin.publicAIFeature.edit') }}</h2>
        <div class="space-y-4">
          <!-- 绑定模型下拉框 -->
          <div>
            <label class="block text-sm font-medium mb-1">{{ t('admin.publicAIFeature.boundModel') }}</label>
            <div class="text-xs text-gray-500 mb-2">
              {{ t('admin.publicAIFeature.modelTypeLabel') }}:
              <span class="font-medium">{{ t(`admin.publicAIFeature.modelTypes.${editingFeature?.model_type || 'chat'}`) }}</span>
            </div>
            <select v-model="editForm.model_config_id" class="w-full border rounded px-3 py-2">
              <option value="">{{ t('admin.publicAIFeature.unbound') }}（{{ t('admin.publicAIFeature.useFallback') }}）</option>
              <option v-for="m in editModels" :key="m.id" :value="m.id">{{ m.label }}</option>
            </select>
            <p class="text-xs text-gray-400 mt-1">{{ t('admin.publicAIFeature.boundModelHint') }}</p>
          </div>
          <!-- 降级档位 -->
          <div>
            <label class="block text-sm font-medium mb-1">{{ t('admin.publicAIFeature.fallbackTier') }}</label>
            <select v-model="editForm.fallback_tier" class="w-full border rounded px-3 py-2">
              <option v-for="tier in fallbackTiers" :key="tier.value" :value="tier.value">{{ tier.label }}</option>
            </select>
            <p class="text-xs text-gray-400 mt-1">{{ t('admin.publicAIFeature.fallbackTierHint') }}</p>
          </div>
          <!-- 开关 -->
          <div>
            <label class="flex items-center gap-2">
              <input type="checkbox" v-model="editForm.enabled" />
              <span class="text-sm font-medium">{{ t('common.enabled') }}</span>
            </label>
            <p class="text-xs text-gray-400 mt-1">{{ t('admin.publicAIFeature.enabledHint') }}</p>
          </div>
        </div>
        <div class="flex justify-end gap-3 mt-6">
          <button class="px-4 py-2 border rounded hover:bg-gray-50" @click="cancelEdit">{{ t('common.cancel') }}</button>
          <button class="px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50"
                  :disabled="saving" @click="saveFeature">
            {{ saving ? t('common.saving') : t('common.save') }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>
