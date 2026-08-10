<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { apiPrefix } from '@/config'
import { useGetLanguageModel, useGetLanguageModels } from '@/hooks/use-language-model'
import { useI18n } from 'vue-i18n'

type ModelForm = {
  selectValue: string
  provider: string
  model: string
  parameters: Record<string, string | number | boolean | undefined>
}

const props = defineProps({
  model_config: {
    type: Object,
    default: () => ({}),
    required: true,
  },
})
const emits = defineEmits(['update:model_config'])
const { t } = useI18n()
const popupVisible = ref(false)
const form = ref<ModelForm>({
  selectValue: '',
  provider: '',
  model: '',
  parameters: {},
})
const {
  loading: getLanguageModelLoading,
  language_model,
  loadLanguageModel,
} = useGetLanguageModel()
const { language_models, loadLanguageModels } = useGetLanguageModels()
const modelOptions = computed(() => {
  return language_models.value.map((language_model) => {
    return {
      isGroup: true,
      label: language_model.label,
      options: language_model.models.map((model) => {
        return {
          label: model.label,
          value: `${language_model.name}/${model.model_name}`,
        }
      }),
    }
  })
})

// 将模型参数的 options（value 为 unknown）收窄为 a-select 可接受的选项
const getParameterOptions = (
  parameter: { options?: Array<{ label: string; value: unknown }> } | undefined,
): Array<{ label: string; value: string | number | boolean }> =>
  (parameter?.options ?? []).map((opt) => ({
    label: opt.label,
    value: opt.value as string | number | boolean,
  }))

const asSelectValue = (value: unknown): string | number | boolean | undefined =>
  value as string | number | boolean | undefined
const asNumberValue = (value: unknown): number | undefined =>
  typeof value === 'number' ? value : undefined
const asStringValue = (value: unknown): string | undefined =>
  typeof value === 'string' ? value : undefined

const syncFormFromProps = (value: Record<string, unknown>) => {
  form.value.selectValue = value?.provider && value?.model ? `${value.provider}/${value.model}` : ''
  form.value.provider = String(value?.provider || '')
  form.value.model = String(value?.model || '')
  form.value.parameters = (value?.parameters || {}) as Record<string, string | number | boolean | undefined>
}

const changeModel = (value: string | number | boolean | Record<string, unknown> | (string | number | boolean | Record<string, unknown>)[]) => {
  const [provider_name, model_name] = (value as string).split('/')

  loadLanguageModel(provider_name, model_name).then(() => {
    form.value.provider = provider_name
    form.value.model = model_name
    form.value.parameters = language_model.value.parameters.reduce(
      (acc, parameter) => {
        acc[parameter.name] = (parameter.default ?? null) as string | number | boolean | undefined
        return acc
      },
      {} as Record<string, string | number | boolean | undefined>,
    )
  })
}

const handleApply = () => {
  const [provider_name, model_name] = form.value.selectValue.split('/')
  if (!provider_name || !model_name) return

  emits('update:model_config', {
    provider: provider_name,
    model: model_name,
    parameters: form.value.parameters,
  })
  popupVisible.value = false
}

watch(
  () => props.model_config,
  (newValue) => {
    syncFormFromProps((newValue || {}) as Record<string, unknown>)
    if (newValue?.provider && newValue?.model) {
      void loadLanguageModel(String(newValue.provider), String(newValue.model))
    }
  },
  { immediate: true },
)

watch(popupVisible, (visible) => {
  if (!visible) return
  syncFormFromProps((props.model_config || {}) as Record<string, unknown>)
  if (props.model_config?.provider && props.model_config?.model) {
    void loadLanguageModel(String(props.model_config.provider), String(props.model_config.model))
  }
})

onMounted(() => {
  void loadLanguageModels()
})
</script>

<template>
  <a-trigger
    v-model:popup-visible="popupVisible"
    trigger="click"
    position="bl"
    :popup-translate="[0, 12]"
  >
    <div class="flex items-center gap-1 cursor-pointer hover:bg-gray-100 px-1.5 py-1 rounded-lg">
      <a-avatar
        v-if="form.provider"
        :size="16"
        shape="square"
        :image-url="`${apiPrefix}/language-models/${form.provider}/icon`"
      />
      <icon-robot v-else />
      <div class="text-gray-700 text-xs">
        {{ form.model || t('appStudio.promptCompareModel.unsetModel') }}
      </div>
      <icon-down />
    </div>
    <template #content>
      <div class="bg-white px-6 py-5 shadow rounded-lg w-[460px]">
        <div class="text-gray-700 text-base font-semibold mb-3">
          {{ t('appStudio.promptCompareModel.title') }}
        </div>
        <div class="flex flex-col gap-2 mb-2">
          <div class="text-gray-700">{{ t('appStudio.promptCompareModel.modelLabel') }}</div>
          <a-select
            v-model:model-value="form.selectValue"
            :options="modelOptions"
            size="small"
            class="rounded-lg mb-2"
            :placeholder="t('appStudio.promptCompareModel.modelPlaceholder')"
            @change="changeModel"
          >
            <template #label="{ data }">
              <div class="flex items-center gap-2">
                <a-avatar
                  :size="16"
                  shape="square"
                  :image-url="`${apiPrefix}/language-models/${data.value.split('/')[0]}/icon`"
                />
                <a-space :size="4">
                  <div class="text-xs text-gray-700">{{ data.value.split('/')[0] }}</div>
                  <div class="text-xs text-gray-500">·</div>
                  <div class="text-xs text-gray-700">{{ data.value.split('/')[1] }}</div>
                </a-space>
              </div>
            </template>
            <template #option="{ data }">
              <div class="flex items-center gap-2">
                <a-avatar
                  :size="16"
                  shape="square"
                  :image-url="`${apiPrefix}/language-models/${data.value.split('/')[0]}/icon`"
                />
                <div class="text-xs text-gray-700 py-2">{{ data.label }}</div>
              </div>
            </template>
          </a-select>
        </div>

        <div class="text-gray-700 mb-2">{{ t('appStudio.promptCompareModel.parametersTitle') }}</div>
        <a-spin :loading="getLanguageModelLoading" class="w-full">
          <div
            v-for="parameter in language_model?.parameters"
            :key="parameter.name"
            class="flex items-center gap-2 h-8 mb-4"
          >
            <div class="flex items-center gap-2 text-gray-500 w-[120px] flex-shrink-0">
              <div class="text-xs">{{ parameter?.label }}</div>
              <a-tooltip :content="parameter?.help">
                <icon-question-circle />
              </a-tooltip>
            </div>
            <template v-if="parameter?.options?.length > 0">
              <a-select
                v-model:model-value="form.parameters[parameter.name]"
                :default-value="asSelectValue(parameter.default)"
                :placeholder="t('appStudio.promptCompareModel.parameterPlaceholder')"
                :options="getParameterOptions(parameter)"
              />
            </template>
            <template v-else-if="parameter.type === 'boolean'">
              <a-select
                v-model:model-value="form.parameters[parameter.name]"
                :default-value="asSelectValue(parameter.default)"
                :placeholder="t('appStudio.promptCompareModel.parameterPlaceholder')"
                :options="[
                  { label: t('appStudio.modelConfig.booleanYes'), value: true },
                  { label: t('appStudio.modelConfig.booleanNo'), value: false },
                ]"
              />
            </template>
            <template v-else-if="['int', 'float'].includes(parameter.type)">
              <a-slider
                :model-value="asNumberValue(form.parameters[parameter.name])"
                @update:model-value="(value) => { form.parameters[parameter.name] = value as number }"
                :default-value="parameter.default as number"
                :min="parameter?.min"
                :max="parameter?.max"
                :step="parameter?.type === 'float' ? 0.1 : 1"
                show-input
              />
            </template>
            <template v-else-if="parameter.type === 'string'">
              <a-input
                :model-value="asStringValue(form.parameters[parameter.name])"
                @update:model-value="(value) => { form.parameters[parameter.name] = value }"
                :default-value="parameter.default as string"
                :placeholder="t('appStudio.promptCompareModel.parameterInputPlaceholder')"
              />
            </template>
          </div>
        </a-spin>

        <div class="flex justify-end gap-2 pt-2">
          <a-button class="rounded-lg" @click="popupVisible = false">
            {{ t('common.actions.cancel') }}
          </a-button>
          <a-button type="primary" class="rounded-lg" @click="handleApply">
            {{ t('appStudio.promptCompareModel.applyModel') }}
          </a-button>
        </div>
      </div>
    </template>
  </a-trigger>
</template>
