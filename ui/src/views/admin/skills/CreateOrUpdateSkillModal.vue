<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { Form, Message, type ValidatedError } from '@arco-design/web-vue'
import { useI18n } from 'vue-i18n'
import { getErrorMessage } from '@/utils/error'
import {
  createAdminSkill,
  updateAdminSkill,
  type CreateSkillPackagePayload,
  type SkillToolDefinition,
} from '@/services/admin-skills'
import type { SkillPackage } from '@/models/skill'

type SkillForm = {
  source_key: string
  name: string
  label: string
  description: string
  category: string
  icon: string
  executor_type: 'scf' | 'prompt'
  enabled: boolean
  readme: string
  skill_code: string
  tools_text: string
  tags_text: string
  cap_code: boolean
  cap_network: boolean
  cap_file_output: boolean
}

const props = defineProps({
  skill_id: { type: String, default: '', required: false },
  visible: { type: Boolean, required: true },
  skill: { type: Object as () => SkillPackage | null, default: null, required: false },
  callback: { type: Function, required: false },
})

const emits = defineEmits(['update:visible', 'update:skill_id'])
const { t } = useI18n()

const formRef = ref<InstanceType<typeof Form>>()
const submitLoading = ref(false)

const defaultForm = (): SkillForm => ({
  source_key: '',
  name: '',
  label: '',
  description: '',
  category: '通用',
  icon: '',
  executor_type: 'prompt',
  enabled: true,
  readme: '',
  skill_code: '',
  tools_text: '[]',
  tags_text: '',
  cap_code: false,
  cap_network: false,
  cap_file_output: false,
})

const form = ref<SkillForm>(defaultForm())

const isEditMode = computed(() => Boolean(props.skill_id))
const isScfType = computed(() => form.value.executor_type === 'scf')

const hideModal = () => emits('update:visible', false)

/**
 * 从 props.skill 加载编辑数据（用于编辑模式）。
 */
const loadSkillToForm = (skill: SkillPackage | null) => {
  if (!skill) {
    form.value = defaultForm()
    return
  }
  const caps = (skill.capabilities || {}) as Record<string, boolean>
  form.value = {
    source_key: skill.source_key || '',
    name: skill.name || '',
    label: skill.label || '',
    description: skill.description || '',
    category: skill.category || '通用',
    icon: skill.icon || '',
    executor_type: (skill.executor_type === 'scf' ? 'scf' : 'prompt') as 'scf' | 'prompt',
    enabled: skill.enabled !== false,
    readme: skill.readme || '',
    skill_code: skill.skill_code || '',
    tools_text: JSON.stringify(skill.tools || [], null, 2),
    tags_text: (skill.tags || []).join(', '),
    cap_code: Boolean(caps.code),
    cap_network: Boolean(caps.network),
    cap_file_output: Boolean(caps.file_output),
  }
}

watch(
  () => props.visible,
  (visible) => {
    if (visible) {
      if (isEditMode.value && props.skill) {
        loadSkillToForm(props.skill)
      } else {
        form.value = defaultForm()
      }
    }
  },
)

const parseTools = (text: string): SkillToolDefinition[] => {
  const normalized = String(text || '').trim()
  if (!normalized) return []
  const parsed = JSON.parse(normalized)
  if (!Array.isArray(parsed)) {
    throw new Error('tools must be a JSON array')
  }
  return parsed
    .filter((item: Record<string, unknown>) => item && typeof item === 'object' && item.name)
    .map((item: Record<string, unknown>) => ({
      name: String(item.name),
      label: String(item.label || item.name),
      description: String(item.description || ''),
      entrypoint: String(item.entrypoint || item.name),
      input_schema: item.input_schema || item.inputSchema || {},
    }))
}

const parseTags = (text: string): string[] => {
  return String(text || '')
    .split(/[,，]/)
    .map((tag) => tag.trim())
    .filter(Boolean)
}

/**
 * 一键加载 scf 类型的 skill.py + tools 模板，便于用户参考。
 */
const loadScfTemplate = () => {
  form.value.skill_code = `"""技能包示例代码。"""

from __future__ import annotations

from typing import Any


def run(params: dict[str, Any]) -> dict[str, Any]:
    """示例入口函数。

    Args:
        params: 由 input_schema 描述的输入对象。

    Returns:
        可 JSON 序列化的 dict。
    """
    request = str(params.get("request", "") or "").strip()
    return {
        "summary": request or "未提供输入",
        "echo": True,
    }
`
  form.value.tools_text = JSON.stringify(
    [
      {
        name: 'run',
        label: '执行',
        description: '示例工具：接收 request 参数并返回结构化结果。',
        entrypoint: 'run',
        input_schema: {
          type: 'object',
          properties: {
            request: {
              type: 'string',
              description: '用户请求文本',
            },
          },
          required: ['request'],
        },
      },
    ],
    null,
    2,
  )
}

const handleSubmit = async (errors: undefined | Record<string, ValidatedError>) => {
  if (errors) return false
  submitLoading.value = true
  try {
    let tools: SkillToolDefinition[] = []
    if (isScfType.value) {
      tools = parseTools(form.value.tools_text)
    }
    const tags = parseTags(form.value.tags_text)
    const capabilities: Record<string, boolean> = {}
    if (form.value.cap_code) capabilities.code = true
    if (form.value.cap_network) capabilities.network = true
    if (form.value.cap_file_output) capabilities.file_output = true

    const payload: CreateSkillPackagePayload = {
      source_key: form.value.source_key,
      name: form.value.name,
      label: form.value.label,
      description: form.value.description,
      category: form.value.category,
      icon: form.value.icon,
      executor_type: form.value.executor_type,
      enabled: form.value.enabled,
      readme: form.value.readme,
      skill_code: isScfType.value ? form.value.skill_code : '',
      tools,
      tags,
      capabilities,
    }

    if (isEditMode.value) {
      const updatePayload: Omit<CreateSkillPackagePayload, 'source_key'> = { ...payload }
      delete (updatePayload as Record<string, unknown>).source_key
      await updateAdminSkill(props.skill_id, updatePayload)
      Message.success(t('admin.skillsAdmin.updateSuccess'))
    } else {
      await createAdminSkill(payload)
      Message.success(t('admin.skillsAdmin.createSuccess'))
    }
    if (props.callback) await props.callback()
    hideModal()
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.skillsAdmin.saveFailed')))
    return false
  } finally {
    submitLoading.value = false
  }
}

const handleSubmitClick = async () => {
  const validate = formRef.value?.validate
  if (validate) {
    const errors = await validate()
    if (errors) return
  }
  await handleSubmit(undefined)
}
</script>

<template>
  <a-modal
    :visible="visible"
    :width="820"
    :title="isEditMode ? t('admin.skillsAdmin.editTitle') : t('admin.skillsAdmin.createTitle')"
    :mask-closable="false"
    :ok-loading="submitLoading"
    @cancel="hideModal"
    @ok="handleSubmitClick"
  >
    <a-form ref="formRef" :model="form" layout="vertical" class="space-y-4">
      <!-- executor_type 切换提示 -->
      <a-alert v-if="!isScfType" type="info" :show-icon="true" class="!mb-2">
        {{ t('admin.skillsAdmin.promptTypeHint') }}
      </a-alert>
      <a-alert v-else type="warning" :show-icon="true" class="!mb-2">
        {{ t('admin.skillsAdmin.scfTypeHint') }}
      </a-alert>

      <a-row :gutter="16">
        <a-col :span="12">
          <a-form-item
            field="source_key"
            :label="t('admin.skillsAdmin.sourceKey')"
            :rules="[{ required: true, message: t('admin.skillsAdmin.sourceKeyRequired') }]"
            :extra="t('admin.skillsAdmin.sourceKeyExtra')"
          >
            <a-input
              v-model="form.source_key"
              :placeholder="t('admin.skillsAdmin.sourceKeyPlaceholder')"
              :disabled="isEditMode"
            />
          </a-form-item>
        </a-col>
        <a-col :span="12">
          <a-form-item field="category" :label="t('admin.skillsAdmin.category')">
            <a-input v-model="form.category" :placeholder="t('admin.skillsAdmin.categoryPlaceholder')" />
          </a-form-item>
        </a-col>
      </a-row>

      <a-row :gutter="16">
        <a-col :span="12">
          <a-form-item field="name" :label="t('admin.skillsAdmin.name')">
            <a-input v-model="form.name" :placeholder="t('admin.skillsAdmin.namePlaceholder')" />
          </a-form-item>
        </a-col>
        <a-col :span="12">
          <a-form-item field="label" :label="t('admin.skillsAdmin.label')">
            <a-input v-model="form.label" :placeholder="t('admin.skillsAdmin.labelPlaceholder')" />
          </a-form-item>
        </a-col>
      </a-row>

      <a-form-item field="description" :label="t('admin.skillsAdmin.descriptionLabel')">
        <a-textarea
          v-model="form.description"
          :placeholder="t('admin.skillsAdmin.descriptionPlaceholder')"
          :auto-size="{ minRows: 2, maxRows: 4 }"
        />
      </a-form-item>

      <a-row :gutter="16">
        <a-col :span="12">
          <a-form-item field="icon" :label="t('admin.skillsAdmin.icon')">
            <a-input v-model="form.icon" :placeholder="t('admin.skillsAdmin.iconPlaceholder')" />
          </a-form-item>
        </a-col>
        <a-col :span="6">
          <a-form-item field="executor_type" :label="t('admin.skillsAdmin.executorType')">
            <a-select v-model="form.executor_type">
              <a-option value="prompt">{{ t('admin.skillsAdmin.executorTypes.prompt') }}</a-option>
              <a-option value="scf">{{ t('admin.skillsAdmin.executorTypes.scf') }}</a-option>
            </a-select>
          </a-form-item>
        </a-col>
        <a-col :span="6">
          <a-form-item field="enabled" :label="t('admin.skillsAdmin.status')">
            <a-switch v-model="form.enabled" />
          </a-form-item>
        </a-col>
      </a-row>

      <!-- 能力声明 -->
      <a-form-item :label="t('admin.skillsAdmin.capabilities')">
        <a-space wrap>
          <a-checkbox v-model="form.cap_code">{{ t('admin.skillsAdmin.capCode') }}</a-checkbox>
          <a-checkbox v-model="form.cap_network">{{ t('admin.skillsAdmin.capNetwork') }}</a-checkbox>
          <a-checkbox v-model="form.cap_file_output">{{ t('admin.skillsAdmin.capFileOutput') }}</a-checkbox>
        </a-space>
        <template #extra>
          <span class="text-xs text-gray-500">{{ t('admin.skillsAdmin.capabilitiesHint') }}</span>
        </template>
      </a-form-item>

      <a-form-item field="tags_text" :label="t('admin.skillsAdmin.tags')">
        <a-input v-model="form.tags_text" :placeholder="t('admin.skillsAdmin.tagsPlaceholder')" />
      </a-form-item>

      <a-form-item field="readme" :label="t('admin.skillsAdmin.readme')">
        <a-textarea
          v-model="form.readme"
          :placeholder="t('admin.skillsAdmin.readmePlaceholder')"
          :auto-size="{ minRows: 4, maxRows: 12 }"
        />
      </a-form-item>

      <template v-if="isScfType">
        <a-form-item :label="t('admin.skillsAdmin.skillCode')">
          <div class="flex items-center justify-between mb-1">
            <span class="text-xs text-gray-500">{{ t('admin.skillsAdmin.skillCodeHint') }}</span>
            <a-button size="mini" type="text" @click="loadScfTemplate">
              {{ t('admin.skillsAdmin.loadTemplate') }}
            </a-button>
          </div>
          <a-textarea
            v-model="form.skill_code"
            :placeholder="t('admin.skillsAdmin.skillCodePlaceholder')"
            :auto-size="{ minRows: 8, maxRows: 24 }"
            class="font-mono text-xs"
          />
        </a-form-item>

        <a-form-item :label="t('admin.skillsAdmin.toolsDefinition')">
          <a-textarea
            v-model="form.tools_text"
            :placeholder="t('admin.skillsAdmin.toolsDefinitionPlaceholder')"
            :auto-size="{ minRows: 6, maxRows: 20 }"
            class="font-mono text-xs"
          />
          <template #extra>
            <div class="text-xs text-gray-500 leading-5">
              <div>{{ t('admin.skillsAdmin.toolsDefinitionHint') }}</div>
              <div class="mt-1 text-amber-600">{{ t('admin.skillsAdmin.entrypointMatchHint') }}</div>
            </div>
          </template>
        </a-form-item>
      </template>
    </a-form>
  </a-modal>
</template>
