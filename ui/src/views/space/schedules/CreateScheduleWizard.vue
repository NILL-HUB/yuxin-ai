<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { Message } from '@arco-design/web-vue'
import { useI18n } from 'vue-i18n'
import dayjs, { type Dayjs } from 'dayjs'
import { getErrorMessage } from '@/utils/error'
import {
  calendarFromInterval,
  cronFromCalendar,
  intervalConfigFromCalendar,
  isIntervalCalendar,
  type CalendarType,
} from './calendar-mapping'
import {
  createScheduleTask,
  humanizeScheduleCron,
  parseScheduleIntent,
  updateScheduleTask,
  type IntervalConfig,
  type ScheduleParseResult,
  type ScheduleTaskItem,
} from '@/services/schedule-task'

type HistoryTurn = { user: string; assistant: string }

const props = defineProps<{
  visible: boolean
  task?: ScheduleTaskItem | null
}>()

const emit = defineEmits<{
  'update:visible': [value: boolean]
  success: []
  cancel: []
}>()

const { t } = useI18n()
const route = useRoute()

// admin 上下文检测：admin 路由带 realm: 'admin' 且路径以 /admin/ 开头
const isAdminContext = computed(() => route.path.startsWith('/admin') || route.meta.realm === 'admin')

const isEditing = computed(() => Boolean(props.task))

const PRESETS: Array<{ labelKey: string; cron: string; humanized: string }> = [
  { labelKey: 'space.schedules.presetEverySecond', cron: '*/1 * * * * *', humanized: '每秒' },
  { labelKey: 'space.schedules.presetEveryMinute', cron: '0 * * * * *', humanized: '每分钟' },
  { labelKey: 'space.schedules.presetEveryHour', cron: '0 0 * * * *', humanized: '每小时' },
  { labelKey: 'space.schedules.presetEveryDay', cron: '0 0 0 * * *', humanized: '每天 00:00:00' },
  { labelKey: 'space.schedules.presetEveryWeek', cron: '0 0 0 * * 1', humanized: '每周一 00:00:00' },
  { labelKey: 'space.schedules.presetEveryMonth', cron: '0 0 0 1 * *', humanized: '每月1号 00:00:00' },
]

const CRON_FIELD_LABELS = ['sec', 'min', 'hour', 'day', 'month', 'week'] as const

const currentStep = ref(0)
const parsing = ref(false)
const syncingHumanized = ref(false)
const saving = ref(false)

const userInput = ref('')
const answerInput = ref('')
const parseResult = ref<ScheduleParseResult | null>(null)
const history = ref<HistoryTurn[]>([])

const taskName = ref('')
const refinedPrompt = ref('')
const cronParts = ref<string[]>(['*', '*', '*', '*', '*', '*'])
const cronHumanized = ref('')

// 触发类型：cron（定时表达式）或 interval（间隔触发）
const triggerType = ref<'cron' | 'interval'>('cron')
const intervalUnit = ref<IntervalConfig['unit']>('hour')
const intervalEvery = ref(1)
const intervalDayOfMonth = ref(1)
const intervalDayOfWeek = ref(1)
const intervalHours = ref(0)
const intervalMinutes = ref(0)

// 日历快速设置状态：周期类型 + 每 N 个周期 + 时间 + 周几(可多选)/每月几号/分点
const calType = ref<CalendarType>('day')
const calEvery = ref(1)
const calTime = ref<Dayjs>(dayjs().hour(0).minute(0).second(0))
const calWeekdays = ref<number[]>([1])
const calDayOfMonth = ref(1)
const calMinutes = ref(0)
const WEEKDAY_OPTIONS = Array.from({ length: 7 }, (_, i) => ({
  value: i + 1,
  label: t(`space.schedules.weekday.${i + 1}`),
}))
const DAY_OPTIONS = Array.from({ length: 31 }, (_, i) => ({ value: i + 1, label: `${i + 1}号` }))
const MINUTE_OPTIONS = Array.from({ length: 60 }, (_, i) => ({ value: i, label: `${String(i).padStart(2, '0')}分` }))

// 周期类型对应的中文单位（用于「每 N 天/周/月/分钟/小时」表达）
const calTypeText = computed(() => {
  switch (calType.value) {
    case 'minute':
      return t('space.schedules.intervalUnitMinute')
    case 'hour':
      return t('space.schedules.intervalUnitHour')
    case 'week':
      return t('space.schedules.intervalUnitWeek')
    case 'month':
      return t('space.schedules.intervalUnitMonth')
    default:
      return t('space.schedules.intervalUnitDay')
  }
})

const cronExpression = computed(() => cronParts.value.join(' '))
const missingFields = computed(() => parseResult.value?.missing_fields ?? [])

const buildAssistantText = (result: ScheduleParseResult): string => {
  const humanized = result.cron_humanized || result.cron_expression
  if (result.missing_fields && result.missing_fields.length > 0) {
    return `${humanized}；还需确认：${result.missing_fields.join('；')}`
  }
  return humanized
}

const applyCron = (cron: string) => {
  const parts = String(cron || '')
    .trim()
    .split(/\s+/)
  cronParts.value = parts.length === 6 ? parts : ['*', '*', '*', '*', '*', '*']
}

const applyPreset = (preset: (typeof PRESETS)[number]) => {
  triggerType.value = 'cron'
  applyCron(preset.cron)
  cronHumanized.value = preset.humanized
}

// 根据当前 cron 公式同步日历选择器状态（手填/预设/编辑回填时联动）
const syncCalendarFromCron = () => {
  const [, m, h, d, , w] = cronParts.value
  const hh = h === '*' ? 0 : Number.parseInt(h, 10) || 0
  const mm = m === '*' ? 0 : Number.parseInt(m, 10) || 0
  calTime.value = dayjs().hour(Math.min(hh, 23)).minute(Math.min(mm, 59)).second(0)
  calEvery.value = 1
  if (w !== '*' && w !== '?') {
    calType.value = 'week'
    calWeekdays.value = String(w)
      .split(',')
      .map((part) => Number.parseInt(part, 10) || 0)
      .filter((dow) => dow >= 1 && dow <= 7)
    if (calWeekdays.value.length === 0) calWeekdays.value = [1]
  } else if (d !== '*' && d !== '?') {
    calType.value = 'month'
    calDayOfMonth.value = Number.parseInt(d, 10) || 1
  } else {
    calType.value = 'day'
  }
}

// 根据 interval 配置同步日历选择器状态（编辑回填 / 高级表单修改时联动）
const syncCalendarFromInterval = () => {
  const sel = calendarFromInterval({
    unit: intervalUnit.value,
    every: intervalEvery.value,
    day_of_month: intervalDayOfMonth.value,
    day_of_week: intervalDayOfWeek.value,
    hours: intervalHours.value,
    minutes: intervalMinutes.value,
  })
  calType.value = sel.calType
  calEvery.value = sel.every
  calWeekdays.value = sel.weekdays
  calDayOfMonth.value = sel.dayOfMonth
  calMinutes.value = sel.calMinutes
  if (sel.calType === 'day') {
    calTime.value = dayjs().hour(sel.hour).minute(0).second(0)
  }
}

// 按当前触发类型把状态同步到日历（日历始终展示当前生效配置）
const syncCalendarFromState = () => {
  if (triggerType.value === 'interval') syncCalendarFromInterval()
  else syncCalendarFromCron()
}

// 当前设置的实时摘要（cron 显示描述，interval 显示间隔文案）
const scheduleSummary = computed(() => {
  const every = Math.max(1, Number(intervalEvery.value) || 1)
  if (triggerType.value === 'interval') {
    switch (intervalUnit.value) {
      case 'minute':
        return t('space.schedules.intervalSummaryMinute', { every })
      case 'hour':
        return t('space.schedules.intervalSummaryHour', {
          every,
          minutes: String(Math.min(Math.max(Number(intervalMinutes.value) || 0, 0), 59)).padStart(2, '0'),
        })
      case 'day':
        return t('space.schedules.intervalSummaryDay', {
          every,
          hours: String(Math.min(Number(intervalHours.value) || 0, 23)).padStart(2, '0'),
        })
      case 'week':
        return t('space.schedules.intervalSummaryWeek', {
          every,
          weekday: t(`space.schedules.weekday.${Math.min(Math.max(Number(intervalDayOfWeek.value) || 1, 1), 7)}`),
        })
      case 'month':
        return t('space.schedules.intervalSummaryMonth', {
          every,
          day: Math.min(Math.max(Number(intervalDayOfMonth.value) || 1, 1), 31),
        })
    }
  }
  return cronHumanized.value || parseResult.value?.cron_humanized || cronExpression.value
})

// 时间选择器 change → 同步 calTime（a-time-picker 的 v-model 仅接受字符串/Date）
const handleCalTimeChange = (timeString: string | (string | undefined)[] | undefined) => {
  if (typeof timeString === 'string' && timeString) {
    calTime.value = dayjs(timeString, 'HH:mm')
  }
}

// 日历设置 → 自动生成 cron 或 interval 配置并切换触发类型（每天/每周/每月 = cron；按分钟/按小时/每 N 天周月 = interval）
const applyCalendar = async () => {
  // 每周多选周几（如周一+周五）只能由 cron 表达，N 固定为 1
  const multiWeekday = calType.value === 'week' && calWeekdays.value.length > 1
  const every = multiWeekday ? 1 : Math.max(1, Number(calEvery.value) || 1)
  const sel = {
    calType: calType.value,
    every,
    hour: calTime.value.hour(),
    minute: calTime.value.minute(),
    weekday: calWeekdays.value[0] || 1,
    weekdays: calWeekdays.value,
    dayOfMonth: calDayOfMonth.value,
    calMinutes: calMinutes.value,
  }
  if (isIntervalCalendar(calType.value, every, sel.weekdays)) {
    triggerType.value = 'interval'
    const cfg = intervalConfigFromCalendar(sel)
    applyIntervalConfig(cfg)
    cronHumanized.value = ''
  } else {
    triggerType.value = 'cron'
    applyCron(cronFromCalendar(sel))
    try {
      const res = await humanizeScheduleCron(cronExpression.value, isAdminContext.value)
      cronHumanized.value = res.data.cron_humanized
    } catch {
      // 描述更新失败时保留原描述，公式仍已生效
    }
  }
}

watch([triggerType, cronParts, intervalUnit, intervalEvery, intervalDayOfMonth, intervalDayOfWeek, intervalHours, intervalMinutes], syncCalendarFromState, {
  deep: true,
})

const resetAll = () => {
  currentStep.value = 0
  parsing.value = false
  saving.value = false
  syncingHumanized.value = false
  userInput.value = ''
  answerInput.value = ''
  parseResult.value = null
  history.value = []
  taskName.value = ''
  refinedPrompt.value = ''
  triggerType.value = 'cron'
  intervalUnit.value = 'hour'
  intervalEvery.value = 1
  intervalDayOfMonth.value = 1
  intervalDayOfWeek.value = 1
  intervalHours.value = 0
  intervalMinutes.value = 0
  cronParts.value = ['*', '*', '*', '*', '*', '*']
  cronHumanized.value = ''
  calType.value = 'day'
  calEvery.value = 1
  calTime.value = dayjs().hour(0).minute(0).second(0)
  calWeekdays.value = [1]
  calDayOfMonth.value = 1
  calMinutes.value = 0
}

// 组装 interval_config（仅包含当前单位相关的字段）
const buildIntervalConfig = (): IntervalConfig => {
  const config: IntervalConfig = { unit: intervalUnit.value, every: Math.max(1, Number(intervalEvery.value) || 1) }
  if (intervalUnit.value === 'month') config.day_of_month = Number(intervalDayOfMonth.value) || 1
  if (intervalUnit.value === 'week') config.day_of_week = Number(intervalDayOfWeek.value) || 1
  if (intervalUnit.value === 'day') config.hours = Number(intervalHours.value) || 0
  if (intervalUnit.value === 'hour') config.minutes = Number(intervalMinutes.value) || 0
  return config
}

// 从已有任务回填 interval 表单
const applyIntervalConfig = (config?: IntervalConfig | Record<string, never>) => {
  if (!config || !config.unit) return
  intervalUnit.value = config.unit
  intervalEvery.value = config.every ?? 1
  intervalDayOfMonth.value = config.day_of_month ?? 1
  intervalDayOfWeek.value = config.day_of_week ?? 1
  intervalHours.value = config.hours ?? 0
  intervalMinutes.value = config.minutes ?? 0
}

// 编辑模式：打开时直接回填已有任务，跳到确认步骤
const fillFromTask = () => {
  const task = props.task
  if (!task) return
  taskName.value = task.name || ''
  refinedPrompt.value = task.prompt || ''
  triggerType.value = task.trigger_type === 'interval' ? 'interval' : 'cron'
  if (task.trigger_type === 'interval') {
    applyIntervalConfig(task.interval_config)
  } else {
    applyCron(task.cron_expression || '0 0 0 * * *')
    cronHumanized.value = task.cron_humanized || ''
  }
  syncCalendarFromState()
  parseResult.value = {
    cron_expression: task.cron_expression || '',
    cron_humanized: task.cron_humanized || '',
    task_name: task.name || '',
    prompt: task.prompt || '',
    missing_fields: [],
  }
  currentStep.value = 2
}

const runParse = async (input: string, snapshot: HistoryTurn[]) => {
  parsing.value = true
  try {
    const res = await parseScheduleIntent(input, snapshot, isAdminContext.value)
    const result = res.data
    parseResult.value = result
    history.value = [...snapshot, { user: input, assistant: buildAssistantText(result) }]
    taskName.value = result.task_name || taskName.value || ''
    refinedPrompt.value = result.prompt || ''
    if (result.cron_humanized) cronHumanized.value = result.cron_humanized
    triggerType.value = 'cron'
    applyCron(result.cron_expression)
    return result
  } catch (error: unknown) {
    Message.error(getErrorMessage(error, t('space.schedules.parseFailed')))
    return null
  } finally {
    parsing.value = false
  }
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

// Step1：Agent 辅助建议——用户用自然语言回答追问，多轮对话直至补全
const handleSubmitAnswers = async () => {
  const input = answerInput.value.trim()
  if (!input) {
    Message.warning(t('space.schedules.answerRequired'))
    return
  }
  const result = await runParse(input, history.value)
  answerInput.value = ''
  if (!result) return
  currentStep.value = result.missing_fields.length > 0 ? 1 : 2
}

const backToInput = () => {
  resetAll()
}

// 用当前 cron 公式反向生成时间描述（融合显示的双向联动）
const handleSyncHumanized = async () => {
  const parts = cronParts.value.map((part) => String(part).trim())
  if (parts.some((part) => part === '')) {
    Message.warning(t('space.schedules.cronInvalid'))
    return
  }
  syncingHumanized.value = true
  try {
    const res = await humanizeScheduleCron(parts.join(' '), isAdminContext.value)
    cronHumanized.value = res.data.cron_humanized
    Message.success(t('space.schedules.humanizeSynced'))
  } catch (error: unknown) {
    Message.error(getErrorMessage(error, t('space.schedules.humanizeFailed')))
  } finally {
    syncingHumanized.value = false
  }
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
  const isInterval = triggerType.value === 'interval'
  if (isInterval) {
    if (!(Number(intervalEvery.value) > 0)) {
      Message.warning(t('space.schedules.intervalEveryRequired'))
      return
    }
  } else {
    const parts = cronParts.value.map((part) => String(part).trim())
    if (parts.some((part) => part === '')) {
      Message.warning(t('space.schedules.cronInvalid'))
      return
    }
  }
  saving.value = true
  try {
    const payload = {
      name: taskName.value.trim(),
      prompt: refinedPrompt.value.trim(),
      trigger_type: isInterval ? ('interval' as const) : ('cron' as const),
      cron_expression: isInterval ? '' : cronParts.value.map((part) => String(part).trim()).join(' '),
      cron_humanized: isInterval ? '' : cronHumanized.value || parseResult.value?.cron_humanized || '',
      interval_config: isInterval ? buildIntervalConfig() : {},
    }
    if (isEditing.value && props.task) {
      await updateScheduleTask(props.task.id, payload, isAdminContext.value)
      Message.success(t('space.schedules.updateSuccess'))
    } else {
      await createScheduleTask(payload, isAdminContext.value)
      Message.success(t('space.schedules.createSuccess'))
    }
    emit('success')
    closeModal()
  } catch (error: unknown) {
    Message.error(getErrorMessage(error, isEditing.value ? t('space.schedules.updateFailed') : t('space.schedules.saveFailed')))
  } finally {
    saving.value = false
  }
}

const closeModal = () => {
  resetAll()
  emit('update:visible', false)
  emit('cancel')
}

watch(
  () => props.visible,
  (visible) => {
    if (visible) {
      resetAll()
      if (props.task) {
        fillFromTask()
      }
    }
  },
)
</script>

<template>
  <a-modal
    :visible="props.visible"
    :title="isEditing ? t('space.schedules.wizardTitleEdit') : t('space.schedules.wizardTitle')"
    :footer="false"
    :width="720"
    class="create-schedule-wizard"
    @cancel="closeModal"
  >
    <a-steps :current="currentStep" class="mb-6">
      <a-step :title="t('space.schedules.step1')" :description="t('space.schedules.step1Desc')" />
      <a-step :title="t('space.schedules.step2')" :description="t('space.schedules.step2Desc')" />
      <a-step :title="t('space.schedules.step3')" :description="t('space.schedules.step3Desc')" />
    </a-steps>

    <!-- Step 1：描述需求 -->
    <div v-if="currentStep === 0">
      <a-textarea
        v-model="userInput"
        :placeholder="t('space.schedules.inputPlaceholder')"
        :auto-size="{ minRows: 5, maxRows: 8 }"
      />
      <div class="mt-2 text-xs text-gray-400">{{ t('space.schedules.inputHint') }}</div>
      <div class="flex items-center justify-end gap-3 pt-4">
        <a-button @click="closeModal">{{ t('common.actions.cancel') }}</a-button>
        <a-button type="primary" :loading="parsing" @click="handleParseFirst">
          {{ t('space.schedules.parseButton') }}
        </a-button>
      </div>
    </div>

    <!-- Step 2：Agent 辅助建议（自然语言追问，多轮对话） -->
    <div v-else-if="currentStep === 1">
      <div class="rounded-lg border border-gray-200 bg-gray-50 p-4">
        <div class="mb-3 flex items-center gap-2 text-sm font-semibold text-gray-800">
          <icon-robot class="text-blue-600" />
          {{ t('space.schedules.assistantTitle') }}
        </div>

        <!-- 对话历史 -->
        <div v-for="(turn, index) in history" :key="index" class="mb-3 space-y-2">
          <div class="flex justify-end">
            <div class="max-w-[80%] rounded-xl rounded-br-sm bg-blue-600 px-3 py-2 text-sm text-white">
              {{ turn.user }}
            </div>
          </div>
          <div class="flex items-start gap-2">
            <div class="max-w-[85%] rounded-xl rounded-bl-sm bg-white px-3 py-2 text-sm text-gray-700 border border-gray-200">
              {{ turn.assistant }}
            </div>
          </div>
        </div>

        <!-- Agent 追问 -->
        <div v-if="missingFields.length > 0" class="rounded-lg border border-amber-200 bg-amber-50 p-3">
          <div class="mb-2 text-sm font-medium text-amber-800">{{ t('space.schedules.missingTip') }}</div>
          <ul class="space-y-1 text-sm text-amber-700">
            <li v-for="(field, index) in missingFields" :key="field" class="flex gap-1.5">
              <span class="flex-shrink-0">{{ index + 1 }}.</span>
              <span>{{ field }}</span>
            </li>
          </ul>
        </div>

        <!-- 用户自然语言回答 -->
        <a-textarea
          v-model="answerInput"
          :placeholder="t('space.schedules.answerPrompt')"
          :auto-size="{ minRows: 3, maxRows: 6 }"
          class="mt-3"
          @keydown.enter.exact.prevent="handleSubmitAnswers"
        />
      </div>

      <div class="flex items-center justify-between pt-4">
        <a-button @click="backToInput">{{ t('space.schedules.backToInput') }}</a-button>
        <a-button type="primary" :loading="parsing" @click="handleSubmitAnswers">
          {{ t('space.schedules.submitAnswers') }}
        </a-button>
      </div>
    </div>

    <!-- Step 3：确认创建/编辑 -->
    <div v-else>
      <!-- 执行时间：日历统一设置 + 高级设置折叠 -->
      <div class="mb-4 rounded-lg border border-gray-200 p-4">
        <div class="mb-2 text-sm font-semibold text-gray-800">{{ t('space.schedules.timeSectionTitle') }}</div>
        <div class="mb-3 text-xs text-gray-400">{{ t('space.schedules.timeSectionDesc') }}</div>

        <!-- 日历快速设置（通用周期设置器：每天/每周/每月及每 N 天周月/小时/分钟间隔） -->
        <div class="mb-4 rounded-lg border border-blue-100 bg-blue-50/60 p-3">
          <div class="mb-2 text-sm font-semibold text-gray-800">{{ t('space.schedules.calendarTitle') }}</div>
          <div class="flex flex-wrap items-center gap-3">
            <a-radio-group v-model="calType" type="button" size="small">
              <a-radio value="day">{{ t('space.schedules.calTypeDay') }}</a-radio>
              <a-radio value="week">{{ t('space.schedules.calTypeWeek') }}</a-radio>
              <a-radio value="month">{{ t('space.schedules.calTypeMonth') }}</a-radio>
              <a-radio value="minute">{{ t('space.schedules.calTypeMinute') }}</a-radio>
              <a-radio value="hour">{{ t('space.schedules.calTypeHour') }}</a-radio>
            </a-radio-group>
            <span class="flex-shrink-0 text-sm text-gray-500">{{ t('space.schedules.calEveryLabel') }}</span>
            <a-input-number
              v-model="calEvery"
              :min="1"
              :max="365"
              :disabled="calType === 'week' && calWeekdays.length > 1"
              style="width: 90px"
            />
            <span class="flex-shrink-0 text-sm text-gray-500">{{ calTypeText }}</span>
            <a-time-picker
              v-if="calType === 'day' || calType === 'week' || calType === 'month'"
              :model-value="calTime.format('HH:mm')"
              format="HH:mm"
              style="width: 120px"
              @change="handleCalTimeChange"
            />
            <a-select
              v-if="calType === 'month'"
              v-model="calDayOfMonth"
              :options="DAY_OPTIONS"
              :placeholder="t('space.schedules.calDayLabel')"
              style="width: 110px"
            />
            <a-checkbox-group v-if="calType === 'week'" v-model="calWeekdays" class="flex flex-wrap items-center gap-x-3 gap-y-1">
              <a-checkbox v-for="opt in WEEKDAY_OPTIONS" :key="opt.value" :value="opt.value">
                {{ opt.label }}
              </a-checkbox>
            </a-checkbox-group>
            <template v-if="calType === 'hour'">
              <span class="flex-shrink-0 text-sm text-gray-500">{{ t('space.schedules.calMinuteLabel') }}</span>
              <a-select v-model="calMinutes" :options="MINUTE_OPTIONS" style="width: 110px" />
              <span class="flex-shrink-0 text-sm text-gray-500">{{ t('space.schedules.calMinuteSuffix') }}</span>
            </template>
            <a-button type="primary" size="small" @click="applyCalendar">
              {{ t('space.schedules.applyCalendar') }}
            </a-button>
          </div>
          <div class="mt-2 flex items-center gap-2 text-xs">
            <icon-clock-circle class="text-gray-400" />
            <span class="font-medium text-gray-700">{{ t('space.schedules.currentSetting') }}</span>
            <span class="text-gray-600">{{ scheduleSummary }}</span>
          </div>
          <div class="mt-2 text-xs text-gray-400">{{ t('space.schedules.calendarHint') }}</div>
        </div>

        <!-- 高级设置折叠：触发类型切换 + cron 公式/描述 + interval 微调 -->
        <a-collapse :default-active-key="[]" class="advanced-cron-collapse">
          <a-collapse-item key="advanced" :header="t('space.schedules.advancedSettings')">
            <a-radio-group v-model="triggerType" type="button" size="small" class="mb-4">
              <a-radio value="cron">{{ t('space.schedules.triggerCron') }}</a-radio>
              <a-radio value="interval">{{ t('space.schedules.triggerInterval') }}</a-radio>
            </a-radio-group>

            <!-- cron 高级：描述 + 预设 + 6 段公式 -->
            <div v-if="triggerType === 'cron'">
              <div class="flex items-center gap-2 mb-4">
                <span class="flex-shrink-0 text-sm text-gray-500">{{ t('space.schedules.humanizedLabel') }}</span>
                <a-input
                  v-model="cronHumanized"
                  class="flex-1"
                  :placeholder="t('space.schedules.humanizedPlaceholder')"
                />
                <a-tag color="arcoblue" class="flex-shrink-0">{{ cronExpression }}</a-tag>
                <a-button size="mini" :loading="syncingHumanized" @click="handleSyncHumanized">
                  {{ t('space.schedules.humanizeBtn') }}
                </a-button>
              </div>

              <div class="mb-3">
                <div class="mb-2 text-xs font-medium text-gray-500">{{ t('space.schedules.preset') }}</div>
                <a-space :size="8" wrap>
                  <a-button
                    v-for="preset in PRESETS"
                    :key="preset.cron"
                    size="small"
                    :type="cronExpression === preset.cron ? 'primary' : 'outline'"
                    @click="applyPreset(preset)"
                  >
                    {{ t(preset.labelKey) }}
                  </a-button>
                </a-space>
              </div>

              <div class="grid grid-cols-6 gap-2">
                <div v-for="(part, index) in cronParts" :key="index">
                  <a-input v-model="cronParts[index]" class="w-full text-center" />
                  <div class="mt-1 text-center text-xs text-gray-400">
                    {{ t(`space.schedules.cronFields.${CRON_FIELD_LABELS[index]}`) }}
                  </div>
                </div>
              </div>
              <div class="mt-2 text-xs text-gray-400">{{ t('space.schedules.cronStandardHint') }}</div>
            </div>

            <!-- interval 高级微调 -->
            <div v-else class="rounded-lg border border-green-100 bg-green-50/60 p-3">
              <div class="mb-3 text-sm font-semibold text-gray-800">{{ t('space.schedules.intervalTitle') }}</div>
              <div class="flex flex-wrap items-center gap-3">
                <span class="flex-shrink-0 text-sm text-gray-500">{{ t('space.schedules.intervalEveryLabel') }}</span>
                <a-input-number v-model="intervalEvery" :min="1" :max="365" style="width: 90px" />
                <a-select v-model="intervalUnit" style="width: 130px">
                  <a-option value="minute">{{ t('space.schedules.intervalUnitMinute') }}</a-option>
                  <a-option value="hour">{{ t('space.schedules.intervalUnitHour') }}</a-option>
                  <a-option value="day">{{ t('space.schedules.intervalUnitDay') }}</a-option>
                  <a-option value="week">{{ t('space.schedules.intervalUnitWeek') }}</a-option>
                  <a-option value="month">{{ t('space.schedules.intervalUnitMonth') }}</a-option>
                </a-select>
                <template v-if="intervalUnit === 'month'">
                  <span class="flex-shrink-0 text-sm text-gray-500">{{ t('space.schedules.intervalDayOfMonthLabel') }}</span>
                  <a-input-number v-model="intervalDayOfMonth" :min="1" :max="31" style="width: 90px" />
                </template>
                <template v-else-if="intervalUnit === 'week'">
                  <span class="flex-shrink-0 text-sm text-gray-500">{{ t('space.schedules.intervalDayOfWeekLabel') }}</span>
                  <a-select v-model="intervalDayOfWeek" style="width: 130px">
                    <a-option v-for="(label, idx) in WEEKDAY_OPTIONS" :key="idx" :value="label.value">{{ label.label }}</a-option>
                  </a-select>
                </template>
                <template v-else-if="intervalUnit === 'day'">
                  <span class="flex-shrink-0 text-sm text-gray-500">{{ t('space.schedules.intervalHoursLabel') }}</span>
                  <a-input-number v-model="intervalHours" :min="0" :max="23" style="width: 90px" />
                </template>
                <template v-else-if="intervalUnit === 'hour'">
                  <span class="flex-shrink-0 text-sm text-gray-500">{{ t('space.schedules.intervalMinutesLabel') }}</span>
                  <a-input-number v-model="intervalMinutes" :min="0" :max="59" style="width: 90px" />
                </template>
              </div>
              <div class="mt-2 text-xs text-gray-400">{{ t('space.schedules.intervalHint') }}</div>
            </div>
          </a-collapse-item>
        </a-collapse>
      </div>

      <a-form layout="vertical" class="mb-4" :model="{}">
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
          {{ isEditing ? t('space.schedules.saveChanges') : t('space.schedules.saveTask') }}
        </a-button>
      </div>
    </div>
  </a-modal>
</template>

<style scoped></style>
