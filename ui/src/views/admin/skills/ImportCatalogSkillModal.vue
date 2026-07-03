<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { Message } from '@arco-design/web-vue'
import { useI18n } from 'vue-i18n'
import { getErrorMessage } from '@/utils/error'
import { listCatalogSkills, importCatalogSkill, type CatalogPackage } from '@/services/admin-skills'

const props = defineProps({
  visible: { type: Boolean, required: true },
  callback: { type: Function, required: false },
})

const emits = defineEmits(['update:visible'])
const { t } = useI18n()

const loading = ref(false)
const importing = ref(false)
const packages = ref<CatalogPackage[]>([])
const searchWord = ref('')
const selectedSourceKey = ref('')

const hideModal = () => emits('update:visible', false)

const filteredPackages = computed(() => {
  const word = searchWord.value.trim().toLowerCase()
  if (!word) return packages.value
  return packages.value.filter((pkg) => {
    return (
      pkg.source_key.toLowerCase().includes(word) ||
      pkg.name.toLowerCase().includes(word) ||
      pkg.label.toLowerCase().includes(word) ||
      pkg.description.toLowerCase().includes(word) ||
      pkg.category.toLowerCase().includes(word)
    )
  })
})

const notImportedCount = computed(() => packages.value.filter((pkg) => !pkg.imported).length)

const loadPackages = async () => {
  loading.value = true
  try {
    packages.value = await listCatalogSkills()
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.skillsAdmin.loadCatalogFailed')))
    packages.value = []
  } finally {
    loading.value = false
  }
}

watch(
  () => props.visible,
  (visible) => {
    if (visible) {
      selectedSourceKey.value = ''
      searchWord.value = ''
      void loadPackages()
    }
  },
)

const handleImport = async () => {
  if (!selectedSourceKey.value) {
    Message.warning(t('admin.skillsAdmin.importSelectRequired'))
    return
  }
  importing.value = true
  try {
    await importCatalogSkill(selectedSourceKey.value)
    Message.success(t('admin.skillsAdmin.importSuccess'))
    if (props.callback) await props.callback()
    hideModal()
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.skillsAdmin.importFailed')))
  } finally {
    importing.value = false
  }
}
</script>

<template>
  <a-modal
    :visible="visible"
    :width="780"
    :title="t('admin.skillsAdmin.importTitle')"
    :mask-closable="false"
    :ok-loading="importing"
    :ok-text="t('admin.skillsAdmin.importButton')"
    @cancel="hideModal"
    @ok="handleImport"
  >
    <div class="mb-3 flex items-center justify-between gap-3">
      <a-input
        v-model="searchWord"
        :placeholder="t('admin.skillsAdmin.importSearchPlaceholder')"
        allow-clear
        class="flex-1"
      />
      <span class="text-xs text-gray-500">
        {{ t('admin.skillsAdmin.importCount', { total: packages.length, notImported: notImportedCount }) }}
      </span>
    </div>

    <a-spin :loading="loading" class="w-full">
      <div class="max-h-[420px] overflow-y-auto space-y-2">
        <div
          v-for="pkg in filteredPackages"
          :key="pkg.source_key"
          class="flex cursor-pointer items-start gap-3 rounded-lg border p-3 transition-colors"
          :class="selectedSourceKey === pkg.source_key
            ? 'border-blue-500 bg-blue-50'
            : 'border-slate-200 hover:border-slate-300 hover:bg-slate-50'"
          @click="selectedSourceKey = pkg.source_key"
        >
          <a-radio
            :model-value="selectedSourceKey"
            :value="pkg.source_key"
            class="mt-0.5"
          />
          <div class="flex-1 min-w-0">
            <div class="flex items-center gap-2">
              <span class="text-sm font-semibold text-gray-900">{{ pkg.label || pkg.name }}</span>
              <a-tag v-if="pkg.imported" size="small" color="green">
                {{ t('admin.skillsAdmin.imported') }}
              </a-tag>
              <a-tag size="small" color="gray">{{ pkg.executor_type }}</a-tag>
              <a-tag v-if="pkg.category" size="small" color="blue">{{ pkg.category }}</a-tag>
            </div>
            <div class="mt-0.5 text-xs text-gray-500">{{ pkg.source_key }}</div>
            <div v-if="pkg.description" class="mt-1 text-xs text-gray-600 line-clamp-2">
              {{ pkg.description }}
            </div>
            <div class="mt-1 text-xs text-gray-400">
              v{{ pkg.version }} · {{ t('admin.skillsAdmin.toolCountBadge', { count: pkg.tool_count }) }}
            </div>
          </div>
        </div>
        <a-empty
          v-if="!loading && filteredPackages.length === 0"
          :description="t('admin.skillsAdmin.importEmpty')"
        />
      </div>
    </a-spin>
  </a-modal>
</template>
