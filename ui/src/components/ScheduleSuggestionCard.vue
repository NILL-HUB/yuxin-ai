<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import { Message } from '@arco-design/web-vue'
import { useI18n } from 'vue-i18n'
import { getErrorMessage } from '@/utils/error'
import {
  createScheduleTask,
  parseScheduleIntent,
  rejectScheduleSuggestion,
  type ScheduleParseResult,
} from '@/services/schedule-task'

export type ScheduleSuggestion = {
  app_id: string
  query: string
  similar_count: number
  suggested_prompt: string
  fingerprint: string
}

const props = defineProps<{
  suggestion: ScheduleSuggestion
}>()

const emit = defineEmits<{
  dismiss: []
}>()

const { t } = useI18n()

const PRESETS: Array<{ labelKey: string; cron: string }> = [
  { labelKey: 'space.schedules.presetEverySecond', cron: '*/1 * * * * *' },
  { labelKey: 'space.schedules.presetEveryMinute', cron: '0 * * * * *' },
  { labelKey: 'space.schedules.presetEveryHour', cron: '0 0 * * * *' },
  { labelKey: 'space.schedules.presetEveryDay', cron: '0 0 0 * * *' },
  { labelKey: 'space.schedules.presetEveryWeek', cron: '0 0 0 * * 1' },
  { labelKey: 'space.schedules.presetEveryMonth', cron: '0 0 0 1 * *' },
]

const CRON_FIELD_LABELS = ['sec', 'min', 'hour', 'day', 'month', 'week'] as const

const wizardVisible = ref(false)
const currentStep = ref(0)
const parsing = ref(false)
const saving = ref(false)

const userInput = ref('')
const parseResult = ref<ScheduleParseResult | null>(null)
const history = ref<{ user: string; assistant: string }[]>([])
const answers = reactive<Record<string, string>>({})
const taskName = ref('')
const refinedPrompt = ref('')
const cronParts = ref<string[]>(['*', '*', '*', '*', '*', '*'])

const cronExpression = computed(() => cronParts.value.join(' '))
const missingFields = computed(() => parseResult.value?.missing_fields ?? [])

const buildAssistantText = (result: ScheduleParseResult): string => {
  const humanized = result.cron_humanized || result.cron_expression
  if (result.missing_fields && result.missing_fields.length > 0) {
    return `${humanized}；还需补充：${result.missing_fields.join('、')}`
  }
  return humanized
}

const applyCron = (cron: string) => {
  const parts = String(cron || '')
    .trim()
    .split(/\s+/)
  cronParts.value = parts.length === 6 ? parts : ['*', '*', '*', '*', '*', '*']
}

const resetAll = () => {
  currentStep.value = 0
  parsing.value = false
  saving.value = false
  userInput.value = props.suggestion.query
  parseResult.value = null
  history.value = []
  taskName.value = ''
  refinedPrompt.value = ''
  cronParts.value = ['*', '*', '*', '*', '*', '*']
  for (const key of Object.keys(answers)) {
    delete answers[key]
  }
}

const runParse = async (input: string, snapshot: { user: string; assistant: string }[]) => {
  parsing.value = true
  try {
    const res = await parseScheduleIntent(input, snapshot)
    const result = res.data
    parseResult.value = result
    history.value = [...snapshot, { user: input, assistant: buildAssistantText(result) }]
    taskName.value = result.task_name || taskName.value || ''
    refinedPrompt.value = result.prompt || ''
    applyCron(result.cron_expression)
    return result
  } catch (error: unknown) {
    Message.error(getErrorMessage(error, t('space.schedules.parseFailed')))
    return null
  } finally {
    parsing.value = false
  }
}

const openWizard = () => {
  resetAll()
  wizardVisible.value = true
}

const handleParseFirst = async () => {
  const input = userInput.value.trim()
  if (!input) {
    Message.warning(t('space.schedules.inputRequired'))
    return
  }
  history.value = []
  const result = await runParse(input, [])
  if (!result) return
  currentStep.value = result.missing_fields.length > 0 ? 1 : 2
}

const handleSubmitAnswers = async () => {
  const fields = missingFields.value
  const empty = fields.filter((field) => !String(answers[field] ?? '').trim())
  if (empty.length > 0) {
    Message.warning(t('space.schedules.answerRequired'))
    return
  }
  const question = fields.map((field) => `${field}：${String(answers[field]).trim()}`).join('\n')
  const result = await runParse(question, history.value)
  for (const key of Object.keys(answers)) {
    delete answers[key]
  }
  if (!result) return
  currentStep.value = result.missing_fields.length > 0 ? 1 : 2
}

const backToInput = () => {
  parseResult.value = null
  history.value = []
  taskName.value = ''
  refinedPrompt.value = ''
  cronParts.value = ['*', '*', '*', '*', '*', '*']
  for (const key of Object.keys(answers)) {
    delete answers[key]
  }
  currentStep.value = 0
}

const handleCreate = async () => {
  if (!taskName.value.trim()) {
    Message.warning(t('space.schedules.nameRequired'))
    return
  }
  if (!refinedPrompt.value.trim()) {
    Message.warning(t('space.schedules.promptRequired'))
    return
  }
  const parts = cronParts.value.map((part) => String(part).trim())
  if (parts.some((part) => part === '')) {
    Message.warning(t('space.schedules.cronInvalid'))
    return
  }
  saving.value = true
  try {
    await createScheduleTask({
      name: taskName.value.trim(),
      prompt: refinedPrompt.value.trim(),
      cron_expression: parts.join(' '),
      cron_humanized: parseResult.value?.cron_humanized || '',
    })
    Message.success(t('space.schedules.createSuccess'))
    wizardVisible.value = false
    emit('dismiss')
  } catch (error: unknown) {
    Message.error(getErrorMessage(error, t('space.schedules.saveFailed')))
  } finally {
    saving.value = false
  }
}

const handleIgnore = async () => {
  try {
    await rejectScheduleSuggestion(props.suggestion.fingerprint)
  } catch {
    // 忽略建议失败时不阻塞用户操作
  }
  emit('dismiss')
}

const closeWizard = () => {
  wizardVisible.value = false
}
</script>

<template>
  <div class="rounded-xl border border-orange-200 bg-orange-50 p-4 text-sm text-gray-800 shadow-sm">
    <div class="mb-3 flex items-center justify-between gap-2">
      <span class="font-semibold text-orange-900">{{ t('space.schedules.title') }}</span>
    </div>

    <div class="mb-4 break-all text-gray-700">
      检测到你 {{ suggestion.similar_count }} 次执行「{{ suggestion.query }}」，是否创建为定时任务？
    </div>

    <div class="flex justify-end gap-2">
      <a-button data-test="schedule-suggestion-ignore" @click="handleIgnore">
        忽略
      </a-button>
      <a-button type="primary" data-test="schedule-suggestion-create" @click="openWizard">
        创建定时任务
      </a-button>
    </div>
  </div>

  <a-modal
    :visible="wizardVisible"
    :title="t('space.schedules.wizardTitle')"
    :footer="false"
    :width="680"
    class="create-schedule-wizard"
    @cancel="closeWizard"
  >
    <a-steps :current="currentStep" class="mb-6">
      <a-step :title="t('space.schedules.step1')" :description="t('space.schedules.step1Desc')" />
      <a-step :title="t('space.schedules.step2')" :description="t('space.schedules.step2Desc')" />
      <a-step :title="t('space.schedules.step3')" :description="t('space.schedules.step3Desc')" />
    </a-steps>

    <div v-if="currentStep === 0">
      <a-textarea
        v-model="userInput"
        :placeholder="t('space.schedules.inputPlaceholder')"
        :auto-size="{ minRows: 5, maxRows: 8 }"
      />
      <div class="flex items-center justify-end gap-3 pt-4">
        <a-button @click="closeWizard">{{ t('common.actions.cancel') }}</a-button>
        <a-button type="primary" :loading="parsing" @click="handleParseFirst">
          {{ t('space.schedules.parseButton') }}
        </a-button>
      </div>
    </div>

    <div v-else-if="currentStep === 1">
      <a-alert type="warning" class="mb-4" :title="t('space.schedules.missingTip')" />
      <div v-for="field in missingFields" :key="field" class="mb-3 rounded-lg border border-gray-200 bg-gray-50 p-3">
        <div class="mb-2 text-sm font-medium text-gray-800">{{ field }}</div>
        <a-input v-model="answers[field]" :placeholder="t('space.schedules.answerPlaceholder', { field })" />
      </div>
      <div class="flex items-center justify-between pt-4">
        <a-button @click="backToInput">{{ t('space.schedules.backToInput') }}</a-button>
        <a-button type="primary" :loading="parsing" @click="handleSubmitAnswers">
          {{ t('space.schedules.submitAnswers') }}
        </a-button>
      </div>
    </div>

    <div v-else>
      <div class="mb-4 rounded-lg border border-gray-200 p-4">
        <div class="mb-2 text-sm font-semibold text-gray-800">{{ t('space.schedules.humanizedLabel') }}</div>
        <a-tag color="arcoblue" size="medium">{{ parseResult?.cron_humanized || cronExpression }}</a-tag>
      </div>

      <div class="mb-4">
        <div class="mb-2 text-sm font-semibold text-gray-800">{{ t('space.schedules.preset') }}</div>
        <a-space :size="8" wrap>
          <a-button
            v-for="preset in PRESETS"
            :key="preset.cron"
            size="small"
            :type="cronExpression === preset.cron ? 'primary' : 'outline'"
            @click="applyCron(preset.cron)"
          >
            {{ t(preset.labelKey) }}
          </a-button>
        </a-space>
      </div>

      <a-form layout="vertical" class="mb-4" :model="{}">
        <a-form-item :label="t('space.schedules.cronLabel')">
          <div class="grid grid-cols-6 gap-2">
            <div v-for="(part, index) in cronParts" :key="index">
              <a-input v-model="cronParts[index]" class="w-full text-center" />
              <div class="mt-1 text-center text-xs text-gray-400">
                {{ t(`space.schedules.cronFields.${CRON_FIELD_LABELS[index]}`) }}
              </div>
            </div>
          </div>
          <div class="mt-1 text-xs text-gray-400">{{ t('space.schedules.cronHint') }}</div>
        </a-form-item>
        <a-form-item :label="t('space.schedules.promptLabel')">
          <a-textarea
            v-model="refinedPrompt"
            :auto-size="{ minRows: 3, maxRows: 6 }"
            :placeholder="t('space.schedules.promptPlaceholder')"
          />
        </a-form-item>
        <a-form-item :label="t('space.schedules.nameLabel')">
          <a-input v-model="taskName" :placeholder="t('space.schedules.namePlaceholder')" />
        </a-form-item>
      </a-form>

      <div class="flex items-center justify-between pt-2">
        <a-button @click="backToInput">{{ t('space.schedules.prevStep') }}</a-button>
        <a-button type="primary" :loading="saving" @click="handleCreate">
          {{ t('space.schedules.saveTask') }}
        </a-button>
      </div>
    </div>
  </a-modal>
</template>

<style scoped></style>
