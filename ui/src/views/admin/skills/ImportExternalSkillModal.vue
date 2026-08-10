<script setup lang="ts">
import { ref, watch } from 'vue'
import { Message, type FileItem } from '@arco-design/web-vue'
import { useI18n } from 'vue-i18n'
import { getErrorMessage } from '@/utils/error'
import {
  importSkillFromZip,
  importSkillFromGithub,
  importSkillFromJson,
} from '@/services/admin-skills'

type ImportMethod = 'zip' | 'github' | 'json'

const props = defineProps({
  visible: { type: Boolean, required: true },
  callback: { type: Function, required: false },
})

const emits = defineEmits(['update:visible'])
const { t } = useI18n()

const method = ref<ImportMethod>('zip')
const importing = ref(false)

// zip 上传
const zipFile = ref<File | null>(null)

// github 导入
const githubUrl = ref('')

// json 导入
const configJson = ref('')

// 通用：覆盖开关
const overwrite = ref(false)

const hideModal = () => emits('update:visible', false)

const resetForm = () => {
  method.value = 'zip'
  zipFile.value = null
  githubUrl.value = ''
  configJson.value = ''
  overwrite.value = false
}

watch(
  () => props.visible,
  (visible) => {
    if (visible) {
      resetForm()
    }
  },
)

const handleFileChange = (fileList: FileItem[]) => {
  if (Array.isArray(fileList) && fileList.length > 0) {
    zipFile.value = fileList[0].file ?? null
  } else {
    zipFile.value = null
  }
}

const buildJsonTemplate = () => {
  return JSON.stringify(
    {
      source_key: 'my-skill-v1',
      name: 'my-skill-v1',
      label: '我的技能',
      description: '技能描述',
      category: '通用',
      executor_type: 'prompt',
      enabled: true,
      readme: '# 我的技能\n\n技能说明文档。',
      task_keywords: [],
      capabilities: {},
    },
    null,
    2,
  )
}

const handleLoadTemplate = () => {
  configJson.value = buildJsonTemplate()
}

const handleImport = async () => {
  if (importing.value) return

  // 校验
  if (method.value === 'zip' && !zipFile.value) {
    Message.warning(t('admin.skillsAdmin.importExternal.zipRequired'))
    return
  }
  if (method.value === 'github' && !githubUrl.value.trim()) {
    Message.warning(t('admin.skillsAdmin.importExternal.githubUrlRequired'))
    return
  }
  if (method.value === 'json' && !configJson.value.trim()) {
    Message.warning(t('admin.skillsAdmin.importExternal.jsonRequired'))
    return
  }

  importing.value = true
  try {
    let result
    if (method.value === 'zip') {
      result = await importSkillFromZip(zipFile.value as File, overwrite.value)
    } else if (method.value === 'github') {
      result = await importSkillFromGithub(githubUrl.value.trim(), overwrite.value)
    } else {
      result = await importSkillFromJson(configJson.value.trim(), overwrite.value)
    }

    const importedCount = result?.imported?.length || 0
    const failedCount = result?.failed?.length || 0

    if (importedCount > 0 && failedCount === 0) {
      Message.success(
        t('admin.skillsAdmin.importExternal.importedCount', { count: importedCount }),
      )
    } else if (importedCount > 0 && failedCount > 0) {
      Message.warning(
        t('admin.skillsAdmin.importExternal.partial', {
          imported: importedCount,
          failed: failedCount,
        }),
      )
    } else {
      Message.error(t('admin.skillsAdmin.importExternal.allFailed'))
    }

    if (props.callback) await props.callback()
    hideModal()
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.skillsAdmin.importExternal.failed')))
  } finally {
    importing.value = false
  }
}
</script>

<template>
  <a-modal
    :visible="visible"
    :width="720"
    :title="t('admin.skillsAdmin.importExternal.title')"
    :mask-closable="false"
    :ok-loading="importing"
    :ok-text="t('admin.skillsAdmin.importExternal.okButton')"
    @cancel="hideModal"
    @ok="handleImport"
  >
    <a-radio-group v-model="method" type="button" class="mb-4">
      <a-radio value="zip">{{ t('admin.skillsAdmin.importExternal.tabZip') }}</a-radio>
      <a-radio value="github">{{ t('admin.skillsAdmin.importExternal.tabGithub') }}</a-radio>
      <a-radio value="json">{{ t('admin.skillsAdmin.importExternal.tabJson') }}</a-radio>
    </a-radio-group>

    <!-- zip 上传 -->
    <div v-if="method === 'zip'" class="space-y-2">
      <a-upload
        :file-list="zipFile ? [{ uid: zipFile.name, name: zipFile.name, file: zipFile }] : []"
        :auto-upload="false"
        :show-remove-button="true"
        :limit="1"
        accept=".zip"
        @change="handleFileChange"
      >
        <template #upload-button>
          <a-button type="dashed">
            {{ t('admin.skillsAdmin.importExternal.selectZip') }}
          </a-button>
        </template>
      </a-upload>
      <div class="text-xs text-gray-500">
        {{ t('admin.skillsAdmin.importExternal.zipHint') }}
      </div>
    </div>

    <!-- github URL -->
    <div v-else-if="method === 'github'" class="space-y-2">
      <a-input
        v-model="githubUrl"
        :placeholder="t('admin.skillsAdmin.importExternal.githubUrlPlaceholder')"
        allow-clear
      />
      <div class="text-xs text-gray-500">
        {{ t('admin.skillsAdmin.importExternal.githubHint') }}
      </div>
    </div>

    <!-- JSON 文本 -->
    <div v-else class="space-y-2">
      <div class="flex items-center justify-between">
        <span class="text-sm text-gray-700">
          {{ t('admin.skillsAdmin.importExternal.jsonLabel') }}
        </span>
        <a-button size="mini" type="text" @click="handleLoadTemplate">
          {{ t('admin.skillsAdmin.importExternal.loadTemplate') }}
        </a-button>
      </div>
      <a-textarea
        v-model="configJson"
        :placeholder="t('admin.skillsAdmin.importExternal.jsonPlaceholder')"
        :auto-size="{ minRows: 8, maxRows: 18 }"
        class="font-mono text-xs"
      />
      <div class="text-xs text-gray-500">
        {{ t('admin.skillsAdmin.importExternal.jsonHint') }}
      </div>
    </div>

    <!-- 通用：覆盖开关 -->
    <div class="mt-4 flex items-center gap-2 border-t border-slate-100 pt-3">
      <a-switch v-model="overwrite" />
      <span class="text-sm text-gray-700">
        {{ t('admin.skillsAdmin.importExternal.overwrite') }}
      </span>
      <span class="text-xs text-gray-400">
        {{ t('admin.skillsAdmin.importExternal.overwriteHint') }}
      </span>
    </div>
  </a-modal>
</template>
