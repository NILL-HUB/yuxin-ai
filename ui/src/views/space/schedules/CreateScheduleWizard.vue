<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
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
import { getAppsWithPage } from '@/services/app'

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

// 移动端响应式：<=640px 时弹窗占满屏宽
const isMobile = ref(false)
const updateIsMobile = () => {
  isMobile.value = window.innerWidth <= 640
}
onMounted(() => {
  updateIsMobile()
  window.addEventListener('resize', updateIsMobile)
})
onBeforeUnmount(() => {
  window.removeEventListener('resize', updateIsMobile)
})

const userInput = ref('')
const answerInput = ref('')
const parseResult = ref<ScheduleParseResult | null>(null)
const history = ref<HistoryTurn[]>([])

const taskName = ref('')
const refinedPrompt = ref('')
const boundAppId = ref<string>('')
const userApps = ref<Array<{ id: string; name: string; icon: string }>>([])
const cronParts = ref<string[]>(['*', '*', '*', '*', '*', '*'])
const cronHumanized = ref('')

const loadUserApps = async () => {
  try {
    const res = await getAppsWithPage({
      current_page: 1,
      page_size: 50,
      search_word: '',
      published_only: true,
    })
    userApps.value = (res.data.list || []).map((app) => ({
      id: app.id,
      name: app.name,
      icon: app.icon || '',
    }))
  } catch {
    userApps.value = []
  }
}

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
  boundAppId.value = ''
  userApps.value = []
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
  boundAppId.value = task.app_id || ''
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
      app_id: boundAppId.value || null,
      task_type: boundAppId.value ? ('app_execution' as const) : ('assistant_chat' as const),
      input_params: {},
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
      void loadUserApps()
    }
  },
)
</script>

<template>
  <a-modal
    :visible="props.visible"
    :footer="false"
    hide-title
    :closable="false"
    :mask-closable="true"
    :unmount-on-close="true"
    :width="isMobile ? '100%' : 720"
    modal-class="create-schedule-wizard"
    @cancel="closeModal"
  >
    <!-- 自绘弹窗头（隐藏 Arco 标题，标题栏完全接管） -->
    <div class="csw-head">
      <div class="csw-head-main">
        <span class="csw-head-ico"><icon-schedule /></span>
        <div class="csw-head-text">
          <h3 class="csw-title">
            {{ isEditing ? t('space.schedules.wizardTitleEdit') : t('space.schedules.wizardTitle') }}
          </h3>
          <p class="csw-subtitle">
            {{
              isEditing
                ? '修改已有任务的执行时间、执行对象与执行提示词，保存后立即生效'
                : '用一句话描述要定时做什么，Agent 会帮你解析时间与内容并逐步确认细节'
            }}
          </p>
        </div>
      </div>
      <button type="button" class="csw-head-close" aria-label="关闭" @click="closeModal">
        <icon-close />
      </button>
    </div>

    <!-- 自绘三步步骤条：已完成=对勾浅粉、当前=粉色渐变、未到=灰 -->
    <div class="csw-steps" aria-label="向导步骤">
      <div class="csw-step" :class="{ 'is-active': currentStep === 0, 'is-done': currentStep > 0 }">
        <span class="csw-step-dot">
          <icon-check v-if="currentStep > 0" />
          <span v-else>1</span>
        </span>
        <span class="csw-step-text">
          <span class="csw-step-name">{{ t('space.schedules.step1') }}</span>
          <span class="csw-step-desc">{{ t('space.schedules.step1Desc') }}</span>
        </span>
      </div>
      <span class="csw-step-line" :class="{ 'is-passed': currentStep > 0 }"></span>
      <div class="csw-step" :class="{ 'is-active': currentStep === 1, 'is-done': currentStep > 1 }">
        <span class="csw-step-dot">
          <icon-check v-if="currentStep > 1" />
          <span v-else>2</span>
        </span>
        <span class="csw-step-text">
          <span class="csw-step-name">{{ t('space.schedules.step2') }}</span>
          <span class="csw-step-desc">{{ t('space.schedules.step2Desc') }}</span>
        </span>
      </div>
      <span class="csw-step-line" :class="{ 'is-passed': currentStep > 1 }"></span>
      <div class="csw-step" :class="{ 'is-active': currentStep === 2 }">
        <span class="csw-step-dot">
          <icon-check v-if="currentStep > 2" />
          <span v-else>3</span>
        </span>
        <span class="csw-step-text">
          <span class="csw-step-name">{{ t('space.schedules.step3') }}</span>
          <span class="csw-step-desc">{{ t('space.schedules.step3Desc') }}</span>
        </span>
      </div>
    </div>

    <!-- Step 1：描述需求 -->
    <div v-if="currentStep === 0" class="csw-step-pane">
      <div class="csw-workspace">
        <div class="csw-area-head">
          <span class="csw-area-ico"><icon-message /></span>
          <div>
            <div class="csw-area-title">{{ t('space.schedules.step1') }}</div>
            <div class="csw-area-desc">{{ t('space.schedules.step1Desc') }}</div>
          </div>
        </div>
        <textarea
          v-model="userInput"
          class="csw-textarea"
          :placeholder="t('space.schedules.inputPlaceholder')"
          rows="5"
        ></textarea>
        <div class="csw-hint"><icon-bulb /> {{ t('space.schedules.inputHint') }}</div>
      </div>
      <div class="csw-foot">
        <button type="button" class="csw-btn csw-btn-ghost" @click="closeModal">
          {{ t('common.actions.cancel') }}
        </button>
        <button
          type="button"
          class="csw-btn csw-btn-primary"
          :class="{ 'is-loading': parsing }"
          :disabled="parsing"
          @click="handleParseFirst"
        >
          <icon-loading v-if="parsing" class="csw-btn-spin" />
          {{ t('space.schedules.parseButton') }}
        </button>
      </div>
    </div>

    <!-- Step 2：Agent 辅助建议（自然语言追问，多轮对话） -->
    <div v-else-if="currentStep === 1" class="csw-step-pane">
      <div class="csw-workspace">
        <div class="csw-area-head">
          <span class="csw-area-ico"><icon-robot /></span>
          <div>
            <div class="csw-area-title">{{ t('space.schedules.assistantTitle') }}</div>
            <div class="csw-area-desc">{{ t('space.schedules.step2Desc') }}</div>
          </div>
        </div>

        <!-- 对话历史：用户=粉色气泡右对齐 / 助手=浅底描边左对齐 -->
        <div v-for="(turn, index) in history" :key="index" class="csw-chat">
          <div class="csw-msg csw-msg-user">
            <p>{{ turn.user }}</p>
          </div>
          <div class="csw-msg csw-msg-ai">
            <span class="csw-msg-ai-ico"><icon-robot /></span>
            <p>{{ turn.assistant }}</p>
          </div>
        </div>

        <!-- Agent 追问：琥珀提示卡 -->
        <div v-if="missingFields.length > 0" class="csw-amber">
          <div class="csw-amber-head">
            <icon-exclamation-circle-fill class="csw-amber-ico" />
            <span>{{ t('space.schedules.missingTip') }}</span>
          </div>
          <ul class="csw-amber-list">
            <li v-for="(field, index) in missingFields" :key="field">
              <span class="csw-amber-num">{{ index + 1 }}</span>
              <span>{{ field }}</span>
            </li>
          </ul>
        </div>

        <!-- 用户自然语言回答 -->
        <textarea
          v-model="answerInput"
          class="csw-textarea"
          :placeholder="t('space.schedules.answerPrompt')"
          rows="3"
          @keydown.enter.exact.prevent="handleSubmitAnswers"
        ></textarea>
      </div>

      <div class="csw-foot">
        <button type="button" class="csw-btn csw-btn-ghost" @click="backToInput">
          {{ t('space.schedules.backToInput') }}
        </button>
        <button
          type="button"
          class="csw-btn csw-btn-primary"
          :class="{ 'is-loading': parsing }"
          :disabled="parsing"
          @click="handleSubmitAnswers"
        >
          <icon-loading v-if="parsing" class="csw-btn-spin" />
          {{ t('space.schedules.submitAnswers') }}
        </button>
      </div>
    </div>

    <!-- Step 3：确认创建/编辑 -->
    <div v-else class="csw-step-pane">
      <!-- 执行时间：日历统一设置 + 高级设置折叠 -->
      <div class="csw-card">
        <div class="csw-card-head">
          <span class="csw-card-head-ico"><icon-clock-circle /></span>
          <div>
            <div class="csw-card-title">{{ t('space.schedules.timeSectionTitle') }}</div>
            <div class="csw-card-sub">{{ t('space.schedules.timeSectionDesc') }}</div>
          </div>
        </div>

        <!-- 日历快速设置 -->
        <div class="csw-cal-box">
          <div class="csw-cal-head">
            <span class="csw-cal-title"><icon-clock-circle class="csw-cal-title-ico" />{{ t('space.schedules.calendarTitle') }}</span>
            <span class="csw-cal-tag">日历设置 · 自动生成公式</span>
          </div>

          <!-- 周期类型胶囊单选 -->
          <div class="csw-field-row csw-wrap">
            <div class="csw-pill-group">
              <button
                type="button"
                class="csw-pill"
                :class="{ 'is-active': calType === 'day' }"
                @click="calType = 'day'"
              >
                {{ t('space.schedules.calTypeDay') }}
              </button>
              <button
                type="button"
                class="csw-pill"
                :class="{ 'is-active': calType === 'week' }"
                @click="calType = 'week'"
              >
                {{ t('space.schedules.calTypeWeek') }}
              </button>
              <button
                type="button"
                class="csw-pill"
                :class="{ 'is-active': calType === 'month' }"
                @click="calType = 'month'"
              >
                {{ t('space.schedules.calTypeMonth') }}
              </button>
              <button
                type="button"
                class="csw-pill"
                :class="{ 'is-active': calType === 'minute' }"
                @click="calType = 'minute'"
              >
                {{ t('space.schedules.calTypeMinute') }}
              </button>
              <button
                type="button"
                class="csw-pill"
                :class="{ 'is-active': calType === 'hour' }"
                @click="calType = 'hour'"
              >
                {{ t('space.schedules.calTypeHour') }}
              </button>
            </div>

            <span v-if="calType !== 'minute'" class="csw-frag-label">{{ t('space.schedules.calEveryLabel') }}</span>
            <div v-if="calType !== 'minute'" class="csw-num-wrap csw-num-sm">
              <button
                type="button"
                class="csw-step-btn"
                :disabled="calType === 'week' && calWeekdays.length > 1"
                @click="calEvery = Math.max(1, (Number(calEvery) || 1) - 1)"
              >
                −
              </button>
              <input
                :value="calEvery"
                type="text"
                inputmode="numeric"
                class="csw-num-input"
                :disabled="calType === 'week' && calWeekdays.length > 1"
                @input="calEvery = Number(($event.target as HTMLInputElement).value.replace(/\D/g, '')) || 1"
              />
              <button
                type="button"
                class="csw-step-btn"
                :disabled="calType === 'week' && calWeekdays.length > 1"
                @click="calEvery = Math.min(365, (Number(calEvery) || 1) + 1)"
              >
                +
              </button>
            </div>
            <span v-if="calType !== 'minute'" class="csw-frag-label">{{ calTypeText }}</span>

            <!-- 时间：HH:mm（原生 time input，change 事件同步 calTime） -->
            <input
              v-if="calType === 'day' || calType === 'week' || calType === 'month'"
              :value="calTime.format('HH:mm')"
              type="time"
              class="csw-time-input"
              @change="handleCalTimeChange(($event.target as HTMLInputElement).value)"
            />

            <!-- 每月几号 / 按小时的分钟选择 -->
            <select
              v-if="calType === 'month'"
              :value="calDayOfMonth"
              class="csw-select csw-select-sm"
              @change="calDayOfMonth = Number(($event.target as HTMLSelectElement).value)"
            >
              <option v-for="opt in DAY_OPTIONS" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
            </select>

            <template v-if="calType === 'week'">
              <span class="csw-frag-label">{{ t('space.schedules.calWeekdayLabel') }}</span>
              <div class="csw-pill-group">
                <button
                  v-for="opt in WEEKDAY_OPTIONS"
                  :key="opt.value"
                  type="button"
                  class="csw-pill csw-pill-sm"
                  :class="{ 'is-active': calWeekdays.includes(opt.value) }"
                  @click="
                    calWeekdays.includes(opt.value)
                      ? (calWeekdays = calWeekdays.filter((d) => d !== opt.value))
                      : (calWeekdays = [...calWeekdays, opt.value])
                  "
                >
                  {{ opt.label }}
                </button>
              </div>
            </template>

            <template v-if="calType === 'hour'">
              <span class="csw-frag-label">{{ t('space.schedules.calMinuteLabel') }}</span>
              <select
                :value="calMinutes"
                class="csw-select csw-select-sm"
                @change="calMinutes = Number(($event.target as HTMLSelectElement).value)"
              >
                <option v-for="opt in MINUTE_OPTIONS" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
              </select>
              <span class="csw-frag-label">{{ t('space.schedules.calMinuteSuffix') }}</span>
            </template>

            <button type="button" class="csw-btn csw-btn-primary csw-btn-sm" @click="applyCalendar">
              {{ t('space.schedules.applyCalendar') }}
            </button>
          </div>

          <!-- 当前设置摘要 + 提示 -->
          <div class="csw-cal-summary">
            <span class="csw-cal-summary-ico"><icon-check-circle /></span>
            <span class="csw-cal-summary-key">{{ t('space.schedules.currentSetting') }}</span>
            <span class="csw-cal-summary-val">{{ scheduleSummary }}</span>
          </div>
          <div class="csw-hint"><icon-info-circle /> {{ t('space.schedules.calendarHint') }}</div>
        </div>

        <!-- 高级设置折叠：触发类型切换 + cron 公式/描述 + interval 微调 -->
        <details class="csw-adv">
          <summary class="csw-adv-head">
            <span class="csw-adv-ico"><icon-settings /></span>
            <span class="csw-adv-title">{{ t('space.schedules.advancedSettings') }}</span>
            <span class="csw-adv-chevron"><icon-down /></span>
          </summary>

          <div class="csw-adv-body">
            <div class="csw-pill-group">
              <button
                type="button"
                class="csw-pill"
                :class="{ 'is-active': triggerType === 'cron' }"
                @click="triggerType = 'cron'"
              >
                {{ t('space.schedules.triggerCron') }}
              </button>
              <button
                type="button"
                class="csw-pill"
                :class="{ 'is-active': triggerType === 'interval' }"
                @click="triggerType = 'interval'"
              >
                {{ t('space.schedules.triggerInterval') }}
              </button>
            </div>

            <!-- cron 高级：描述 + 预设 + 6 段公式 -->
            <div v-if="triggerType === 'cron'" class="csw-adv-sec">
              <div class="csw-hr-label">{{ t('space.schedules.humanizedLabel') }}</div>
              <div class="csw-row csw-wrap csw-end">
                <input
                  v-model="cronHumanized"
                  class="csw-input csw-grow"
                  :placeholder="t('space.schedules.humanizedPlaceholder')"
                />
                <code class="csw-mono-chip" :title="t('space.schedules.cronLabel')">{{ cronExpression }}</code>
                <button
                  type="button"
                  class="csw-btn csw-btn-ghost csw-btn-sm"
                  :class="{ 'is-loading': syncingHumanized }"
                  :disabled="syncingHumanized"
                  @click="handleSyncHumanized"
                >
                  <icon-loading v-if="syncingHumanized" class="csw-btn-spin" />
                  {{ t('space.schedules.humanizeBtn') }}
                </button>
              </div>

              <div class="csw-block">
                <div class="csw-label">{{ t('space.schedules.preset') }}</div>
                <div class="csw-pill-group csw-pill-mini">
                  <button
                    v-for="preset in PRESETS"
                    :key="preset.cron"
                    type="button"
                    class="csw-pill csw-pill-mini"
                    :class="{ 'is-active': cronExpression === preset.cron }"
                    @click="applyPreset(preset)"
                  >
                    {{ t(preset.labelKey) }}
                  </button>
                </div>
              </div>

              <div class="csw-block">
                <div class="csw-label">{{ t('space.schedules.cronHint') }}</div>
                <div class="csw-cron-grid">
                  <div v-for="(part, index) in cronParts" :key="index" class="csw-cron-cell">
                    <input v-model="cronParts[index]" class="csw-input csw-cron-input" />
                    <div class="csw-cron-fields">
                      {{ t(`space.schedules.cronFields.${CRON_FIELD_LABELS[index]}`) }}
                    </div>
                  </div>
                </div>
                <div class="csw-note"><icon-info-circle /> {{ t('space.schedules.cronStandardHint') }}</div>
              </div>
            </div>

            <!-- interval 高级微调 -->
            <div v-else class="csw-adv-sec csw-interval-box">
              <div class="csw-label">{{ t('space.schedules.intervalTitle') }}</div>
              <div class="csw-row csw-wrap">
                <span class="csw-frag-label">{{ t('space.schedules.intervalEveryLabel') }}</span>
                <div class="csw-num-wrap">
                  <button
                    type="button"
                    class="csw-step-btn"
                    @click="intervalEvery = Math.max(1, (Number(intervalEvery) || 1) - 1)"
                  >
                    −
                  </button>
                  <input
                    :value="intervalEvery"
                    type="text"
                    inputmode="numeric"
                    class="csw-num-input"
                    @input="intervalEvery = Number(($event.target as HTMLInputElement).value.replace(/\D/g, '')) || 1"
                  />
                  <button
                    type="button"
                    class="csw-step-btn"
                    @click="intervalEvery = Math.min(365, (Number(intervalEvery) || 1) + 1)"
                  >
                    +
                  </button>
                </div>
                <select
                  :value="intervalUnit"
                  class="csw-select"
                  @change="intervalUnit = ($event.target as HTMLSelectElement).value as 'minute' | 'hour' | 'day' | 'week' | 'month'"
                >
                  <option value="minute">{{ t('space.schedules.intervalUnitMinute') }}</option>
                  <option value="hour">{{ t('space.schedules.intervalUnitHour') }}</option>
                  <option value="day">{{ t('space.schedules.intervalUnitDay') }}</option>
                  <option value="week">{{ t('space.schedules.intervalUnitWeek') }}</option>
                  <option value="month">{{ t('space.schedules.intervalUnitMonth') }}</option>
                </select>

                <template v-if="intervalUnit === 'month'">
                  <span class="csw-frag-label">{{ t('space.schedules.intervalDayOfMonthLabel') }}</span>
                  <div class="csw-num-wrap">
                    <button
                      type="button"
                      class="csw-step-btn"
                      @click="intervalDayOfMonth = Math.max(1, (Number(intervalDayOfMonth) || 1) - 1)"
                    >
                      −
                    </button>
                    <input
                      :value="intervalDayOfMonth"
                      type="text"
                      inputmode="numeric"
                      class="csw-num-input"
                      @input="intervalDayOfMonth = Number(($event.target as HTMLInputElement).value.replace(/\D/g, '')) || 1"
                    />
                    <button
                      type="button"
                      class="csw-step-btn"
                      @click="intervalDayOfMonth = Math.min(31, (Number(intervalDayOfMonth) || 1) + 1)"
                    >
                      +
                    </button>
                  </div>
                </template>
                <template v-else-if="intervalUnit === 'week'">
                  <span class="csw-frag-label">{{ t('space.schedules.intervalDayOfWeekLabel') }}</span>
                  <select
                    :value="intervalDayOfWeek"
                    class="csw-select"
                    @change="intervalDayOfWeek = Number(($event.target as HTMLSelectElement).value)"
                  >
                    <option v-for="opt in WEEKDAY_OPTIONS" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
                  </select>
                </template>
                <template v-else-if="intervalUnit === 'day'">
                  <span class="csw-frag-label">{{ t('space.schedules.intervalHoursLabel') }}</span>
                  <div class="csw-num-wrap">
                    <button
                      type="button"
                      class="csw-step-btn"
                      @click="intervalHours = Math.max(0, (Number(intervalHours) || 0) - 1)"
                    >
                      −
                    </button>
                    <input
                      :value="intervalHours"
                      type="text"
                      inputmode="numeric"
                      class="csw-num-input"
                      @input="intervalHours = Math.min(23, Number(($event.target as HTMLInputElement).value.replace(/\D/g, '')) || 0)"
                    />
                    <button
                      type="button"
                      class="csw-step-btn"
                      @click="intervalHours = Math.min(23, (Number(intervalHours) || 0) + 1)"
                    >
                      +
                    </button>
                  </div>
                </template>
                <template v-else-if="intervalUnit === 'hour'">
                  <span class="csw-frag-label">{{ t('space.schedules.intervalMinutesLabel') }}</span>
                  <div class="csw-num-wrap">
                    <button
                      type="button"
                      class="csw-step-btn"
                      @click="intervalMinutes = Math.max(0, (Number(intervalMinutes) || 0) - 1)"
                    >
                      −
                    </button>
                    <input
                      :value="intervalMinutes"
                      type="text"
                      inputmode="numeric"
                      class="csw-num-input"
                      @input="intervalMinutes = Math.min(59, Number(($event.target as HTMLInputElement).value.replace(/\D/g, '')) || 0)"
                    />
                    <button
                      type="button"
                      class="csw-step-btn"
                      @click="intervalMinutes = Math.min(59, (Number(intervalMinutes) || 0) + 1)"
                    >
                      +
                    </button>
                  </div>
                </template>
              </div>
              <div class="csw-note"><icon-info-circle /> {{ t('space.schedules.intervalHint') }}</div>
            </div>
          </div>
        </details>
      </div>

      <!-- 选择要执行的应用：绑定应用=按应用执行；不绑定=通用助手执行 -->
      <div class="csw-card">
        <div class="csw-card-head">
          <span class="csw-card-head-ico"><icon-apps /></span>
          <div>
            <div class="csw-card-title">{{ t('space.schedules.appSectionTitle') }}</div>
            <div class="csw-card-sub">{{ t('space.schedules.appSectionDesc') }}</div>
          </div>
        </div>
        <div class="csw-select-box">
          <icon-common class="csw-select-ico" />
          <select
            :value="boundAppId"
            class="csw-select csw-select-lg"
            @change="boundAppId = ($event.target as HTMLSelectElement).value"
          >
            <option value="">{{ t('space.schedules.appPlaceholder') }}</option>
            <option v-for="app in userApps" :key="app.id" :value="app.id">{{ app.name }}</option>
          </select>
        </div>
        <div class="csw-hint csw-app-state" :class="{ 'is-bound': boundAppId }">
          <icon-check-circle v-if="boundAppId" />
          <icon-robot v-else />
          {{ boundAppId ? t('space.schedules.appBoundHint') : t('space.schedules.appUnboundHint') }}
        </div>
      </div>

      <!-- 精化需求 + 名称 -->
      <div class="csw-card">
        <div class="csw-card-head">
          <span class="csw-card-head-ico"><icon-edit /></span>
          <div>
            <div class="csw-card-title">{{ isEditing ? t('space.schedules.nameLabel') : t('space.schedules.promptLabel') }}</div>
            <div class="csw-card-sub">{{ isEditing ? '核对任务名称与执行提示词' : '核对 Agent 生成的内容并补充任务名称' }}</div>
          </div>
        </div>

        <div class="csw-field">
          <label class="csw-label" for="csw-task-name">
            {{ t('space.schedules.nameLabel') }} <span class="csw-required">*</span>
          </label>
          <input
            id="csw-task-name"
            v-model="taskName"
            type="text"
            class="csw-input"
            :placeholder="t('space.schedules.namePlaceholder')"
          />
        </div>

        <div class="csw-field">
          <label class="csw-label" for="csw-refined-prompt">
            {{ t('space.schedules.promptLabel') }} <span class="csw-required">*</span>
          </label>
          <textarea
            id="csw-refined-prompt"
            v-model="refinedPrompt"
            class="csw-textarea"
            :placeholder="t('space.schedules.promptPlaceholder')"
            rows="4"
          ></textarea>
        </div>
      </div>

      <div class="csw-foot">
        <button type="button" class="csw-btn csw-btn-ghost" @click="backToInput">
          {{ t('space.schedules.prevStep') }}
        </button>
        <button
          type="button"
          class="csw-btn csw-btn-primary"
          :class="{ 'is-loading': saving }"
          :disabled="saving"
          @click="handleCreate"
        >
          <icon-loading v-if="saving" class="csw-btn-spin" />
          {{ isEditing ? t('space.schedules.saveChanges') : t('space.schedules.saveTask') }}
        </button>
      </div>
    </div>
  </a-modal>
</template>

<style scoped>
/* ============================================================
   创建定时任务向导 · 自绘主题样式
   对齐 aicss 变量 / Barbie 粉色主题；不使用 Arco 原生控件视觉
   modal 外壳样式见文末非 scoped 块（modal 经 Teleport 渲染）
   ============================================================ */

/* ---------- 布局节奏 ---------- */
.csw-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  padding: 22px 28px 16px;
  border-bottom: 1px solid var(--aicss-border);
}
.csw-head-main {
  display: flex;
  align-items: center;
  gap: 14px;
  min-width: 0;
}
.csw-head-ico {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 40px;
  height: 40px;
  flex-shrink: 0;
  border-radius: var(--aicss-radius);
  background: var(--aicss-accent-soft);
  color: var(--aicss-accent-text);
  font-size: 20px;
}
.csw-head-ico svg,
.csw-head-ico :deep(svg) {
  width: 20px;
  height: 20px;
}
.csw-head-text {
  min-width: 0;
}
.csw-title {
  margin: 0;
  font-family: var(--aicss-font-serif, Georgia, 'Songti SC', 'SimSun', serif);
  font-size: 18px;
  font-weight: 600;
  line-height: 1.4;
  color: var(--aicss-text);
}
.csw-subtitle {
  margin: 5px 0 0;
  font-size: 12px;
  line-height: 1.5;
  color: var(--aicss-muted);
}
.csw-head-close {
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
.csw-head-close:hover {
  background: var(--aicss-surface-2);
  color: var(--aicss-text);
}
.csw-head-close svg,
.csw-head-close :deep(svg) {
  width: 15px;
  height: 15px;
}

/* ---------- 主体滚动区（头部/底栏外滚动） ---------- */
.csw-step-pane {
  display: flex;
  flex-direction: column;
  gap: 20px;
  padding: 20px 28px 24px;
  overflow-y: auto;
}
.csw-workspace {
  padding: 18px;
  border: 1px solid var(--aicss-border);
  border-radius: var(--aicss-radius);
  background: var(--aicss-surface);
  box-shadow: var(--aicss-shadow-card);
}
.csw-foot {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 12px;
  flex-wrap: wrap;
  padding-top: 4px;
  flex-shrink: 0;
}

/* ---------- 三步步骤条 ---------- */
.csw-steps {
  display: flex;
  align-items: center;
  gap: 0;
  padding: 22px 28px 8px;
}
.csw-step {
  display: flex;
  align-items: center;
  gap: 9px;
  min-width: 0;
  flex: 0 0 auto;
}
.csw-step-dot {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  flex-shrink: 0;
  border-radius: 50%;
  background: var(--aicss-surface-2);
  border: 1px solid var(--aicss-border);
  color: var(--aicss-muted);
  font-size: 12px;
  font-weight: 600;
  font-family: inherit;
  transition:
    background 0.2s ease,
    border-color 0.2s ease,
    color 0.2s ease;
}
.csw-step-dot svg,
.csw-step-dot :deep(svg) {
  width: 12px;
  height: 12px;
}
.csw-step.is-active .csw-step-dot {
  background: linear-gradient(135deg, var(--aicss-accent), #ff5c8d);
  border-color: transparent;
  color: #fff;
  box-shadow: 0 2px 8px rgba(233, 30, 99, 0.35);
}
.csw-step.is-done .csw-step-dot {
  background: var(--aicss-accent-soft);
  border-color: transparent;
  color: var(--aicss-accent-text);
}
.csw-step-text {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}
.csw-step-name {
  font-size: 13px;
  font-weight: 600;
  line-height: 1.2;
  color: var(--aicss-text-2);
}
.csw-step:not(.is-active):not(.is-done) .csw-step-name {
  color: var(--aicss-subtle);
}
.csw-step-desc {
  font-size: 11px;
  line-height: 1.3;
  color: var(--aicss-muted);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.csw-step:not(.is-active):not(.is-done) .csw-step-desc {
  color: var(--aicss-subtle);
}
.csw-step-line {
  height: 2px;
  flex: 1 1 0;
  min-width: 14px;
  margin: 0 10px;
  border-radius: 2px;
  background: var(--aicss-border);
  transition: background 0.3s ease;
}
.csw-step-line.is-passed {
  background: linear-gradient(90deg, var(--aicss-accent), #ff9ec5);
}

/* ---------- 区块头部（面板标题） ---------- */
.csw-area-head {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 14px;
}
.csw-area-ico {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 34px;
  height: 34px;
  flex-shrink: 0;
  border-radius: var(--aicss-radius-sm);
  background: var(--aicss-accent-soft);
  color: var(--aicss-accent-text);
  font-size: 16px;
}
.csw-area-ico svg,
.csw-area-ico :deep(svg) {
  width: 16px;
  height: 16px;
}
.csw-area-title {
  font-size: 14px;
  font-weight: 600;
  line-height: 1.3;
  color: var(--aicss-text);
}
.csw-area-desc {
  margin-top: 2px;
  font-size: 12px;
  line-height: 1.4;
  color: var(--aicss-muted);
}

/* ---------- 自绘按钮 ---------- */
.csw-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  height: 38px;
  padding: 0 18px;
  border: 1px solid transparent;
  border-radius: var(--aicss-radius);
  background: transparent;
  font-family: inherit;
  font-size: 13px;
  font-weight: 500;
  line-height: 1;
  color: var(--aicss-text);
  cursor: pointer;
  white-space: nowrap;
  transition:
    opacity 0.2s ease,
    transform 0.2s ease,
    background 0.2s ease,
    border-color 0.2s ease,
    color 0.2s ease,
    box-shadow 0.2s ease;
}
.csw-btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}
.csw-btn.is-loading {
  opacity: 0.75;
  cursor: progress;
}
.csw-btn-spin {
  animation: csw-rotate 0.9s linear infinite;
}
@keyframes csw-rotate {
  to {
    transform: rotate(360deg);
  }
}
.csw-btn-primary {
  background: linear-gradient(135deg, var(--aicss-accent) 0%, #ff5c8d 100%);
  color: #fff;
  box-shadow: var(--aicss-shadow-card);
}
.csw-btn-primary:hover:not(:disabled) {
  opacity: 0.92;
  transform: translateY(-1px);
}
.csw-btn-primary:active:not(:disabled) {
  transform: translateY(0);
}
.csw-btn-ghost {
  border-color: var(--aicss-border);
  background: var(--aicss-surface);
  color: var(--aicss-text);
}
.csw-btn-ghost:hover:not(:disabled) {
  border-color: var(--aicss-border-strong);
  background: var(--aicss-bg-subtle);
}
.csw-btn-sm {
  height: 32px;
  padding: 0 14px;
  font-size: 12px;
  border-radius: var(--aicss-radius-sm);
}

/* ---------- 自绘输入 / textarea ---------- */
.csw-input,
.csw-textarea {
  width: 100%;
  border: 1px solid var(--aicss-border);
  border-radius: var(--aicss-radius-sm);
  background: var(--aicss-bg-subtle);
  color: var(--aicss-text);
  font-family: inherit;
  font-size: 13px;
  line-height: 1.5;
  box-sizing: border-box;
  outline: none;
  transition:
    border-color 0.2s ease,
    box-shadow 0.2s ease,
    background 0.2s ease;
}
.csw-input {
  height: 38px;
  padding: 0 13px;
}
.csw-textarea {
  min-height: 76px;
  padding: 10px 13px;
  resize: vertical;
  line-height: 1.6;
}
.csw-input::placeholder,
.csw-textarea::placeholder {
  color: var(--aicss-muted);
}
.csw-input:focus,
.csw-textarea:focus {
  border-color: var(--aicss-accent);
  box-shadow: 0 0 0 3px var(--aicss-accent-soft);
  background: var(--aicss-surface);
}
.csw-input:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}
.csw-grow {
  flex: 1 1 auto;
  min-width: 180px;
}
.csw-field {
  margin-bottom: 14px;
}
.csw-field:last-child {
  margin-bottom: 0;
}
.csw-label {
  display: block;
  margin-bottom: 6px;
  font-size: 13px;
  font-weight: 500;
  color: var(--aicss-text);
}
.csw-required {
  color: #f53f3f;
}
.csw-note {
  display: flex;
  align-items: flex-start;
  gap: 5px;
  margin-top: 8px;
  font-size: 12px;
  line-height: 1.5;
  color: var(--aicss-muted);
}
.csw-note svg,
.csw-note :deep(svg) {
  flex-shrink: 0;
  margin-top: 2px;
}

/* ---------- 提示行 ---------- */
.csw-hint {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 10px;
  font-size: 12px;
  line-height: 1.5;
  color: var(--aicss-muted);
}
.csw-hint svg,
.csw-hint :deep(svg) {
  flex-shrink: 0;
  color: var(--aicss-subtle);
}
.csw-hr-label {
  margin-bottom: 8px;
  font-size: 13px;
  font-weight: 600;
  color: var(--aicss-text-2);
}
.csw-block {
  margin-top: 16px;
}
.csw-row {
  display: flex;
  align-items: center;
  gap: 10px;
}
.csw-wrap {
  flex-wrap: wrap;
}
.csw-end {
  justify-content: flex-end;
}

/* ---------- 对话区（Step2） ---------- */
.csw-chat {
  display: flex;
  flex-direction: column;
  gap: 12px;
  margin-bottom: 16px;
}
.csw-msg {
  display: flex;
  max-width: 86%;
}
.csw-msg-user {
  align-self: flex-end;
  justify-content: flex-end;
}
.csw-msg-user p {
  margin: 0;
  padding: 9px 14px;
  border-radius: var(--aicss-radius);
  border-bottom-right-radius: 6px;
  background: linear-gradient(135deg, var(--aicss-accent), #ff5c8d);
  color: #fff;
  font-size: 13px;
  line-height: 1.55;
  box-shadow: var(--aicss-shadow-card);
}
.csw-msg-ai {
  align-self: flex-start;
  align-items: flex-start;
  gap: 8px;
}
.csw-msg-ai-ico {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 26px;
  height: 26px;
  flex-shrink: 0;
  border-radius: 50%;
  background: var(--aicss-accent-soft);
  color: var(--aicss-accent-text);
  font-size: 13px;
}
.csw-msg-ai-ico svg,
.csw-msg-ai-ico :deep(svg) {
  width: 13px;
  height: 13px;
}
.csw-msg-ai p {
  margin: 0;
  padding: 9px 14px;
  border: 1px solid var(--aicss-border);
  border-radius: var(--aicss-radius);
  border-top-left-radius: 6px;
  background: var(--aicss-bg-subtle);
  color: var(--aicss-text-2);
  font-size: 13px;
  line-height: 1.55;
}
.csw-msg p {
  overflow-wrap: break-word;
  white-space: pre-wrap;
}

/* ---------- Agent 追问：琥珀提示卡 ---------- */
.csw-amber {
  margin-bottom: 14px;
  padding: 12px 14px;
  border: 1px solid #f3d19a;
  border-radius: var(--aicss-radius);
  background: linear-gradient(135deg, #fff9ed, #fff4e0);
}
.csw-amber-head {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  font-weight: 600;
  line-height: 1.5;
  color: #8a5a08;
}
.csw-amber-ico {
  flex-shrink: 0;
  color: #d9870f;
  font-size: 14px;
}
.csw-amber-list {
  margin: 8px 0 0;
  padding: 0;
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.csw-amber-list li {
  display: flex;
  align-items: baseline;
  gap: 7px;
  font-size: 12px;
  line-height: 1.5;
  color: #8a6211;
}
.csw-amber-num {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 16px;
  height: 16px;
  padding: 0 4px;
  border-radius: 8px;
  background: #f8e2b5;
  font-size: 11px;
  font-weight: 600;
  color: #8a5a08;
  transform: translateY(1px);
}

/* ---------- Step3 卡片区块 ---------- */
.csw-card {
  padding: 18px;
  border: 1px solid var(--aicss-border);
  border-radius: var(--aicss-radius);
  background: var(--aicss-surface);
  box-shadow: var(--aicss-shadow-card);
}
.csw-card-head {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 14px;
}
.csw-card-head-ico {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 34px;
  height: 34px;
  flex-shrink: 0;
  border-radius: var(--aicss-radius-sm);
  background: var(--aicss-accent-soft);
  color: var(--aicss-accent-text);
  font-size: 16px;
}
.csw-card-head-ico svg,
.csw-card-head-ico :deep(svg) {
  width: 16px;
  height: 16px;
}
.csw-card-title {
  font-size: 14px;
  font-weight: 600;
  line-height: 1.3;
  color: var(--aicss-text);
}
.csw-card-sub {
  margin-top: 2px;
  font-size: 12px;
  line-height: 1.4;
  color: var(--aicss-muted);
}

/* ---------- 日历快速设置区 ---------- */
.csw-cal-box {
  padding: 14px;
  border: 1px solid color-mix(in srgb, var(--aicss-accent) 16%, var(--aicss-border));
  border-radius: var(--aicss-radius);
  background: color-mix(in srgb, var(--aicss-accent) 5%, var(--aicss-surface));
}
.csw-cal-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  flex-wrap: wrap;
  margin-bottom: 12px;
}
.csw-cal-title {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  font-weight: 600;
  color: var(--aicss-text);
}
.csw-cal-title-ico {
  color: var(--aicss-accent-text);
}
.csw-cal-tag {
  padding: 2px 9px;
  border-radius: 999px;
  background: var(--aicss-accent-soft);
  color: var(--aicss-accent-text);
  font-size: 11px;
  font-weight: 500;
  white-space: nowrap;
}
.csw-cal-summary {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  margin-top: 14px;
  padding: 9px 12px;
  border-radius: var(--aicss-radius-sm);
  background: var(--aicss-surface);
  border: 1px solid var(--aicss-border);
  font-size: 12px;
  line-height: 1.5;
}
.csw-cal-summary-ico {
  flex-shrink: 0;
  color: var(--aicss-accent);
}
.csw-cal-summary-ico svg,
.csw-cal-summary-ico :deep(svg) {
  width: 14px;
  height: 14px;
}
.csw-cal-summary-key {
  flex-shrink: 0;
  font-weight: 600;
  color: var(--aicss-text-2);
}
.csw-cal-summary-val {
  color: var(--aicss-text);
  font-weight: 500;
  overflow-wrap: anywhere;
}
.csw-field-row {
  display: flex;
  align-items: center;
  gap: 10px;
}
.csw-field-row.csw-wrap {
  flex-wrap: wrap;
}
.csw-frag-label {
  flex-shrink: 0;
  font-size: 13px;
  color: var(--aicss-text-2);
}

/* ---------- 胶囊单选/多选组 ---------- */
.csw-pill-group {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
}
.csw-pill {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  height: 30px;
  padding: 0 13px;
  border: 1px solid var(--aicss-border);
  border-radius: 999px;
  background: var(--aicss-surface);
  font-family: inherit;
  font-size: 12px;
  font-weight: 500;
  line-height: 1;
  color: var(--aicss-text-2);
  cursor: pointer;
  white-space: nowrap;
  transition:
    border-color 0.2s ease,
    background 0.2s ease,
    color 0.2s ease,
    box-shadow 0.2s ease;
}
.csw-pill:hover {
  border-color: var(--aicss-border-strong);
  background: var(--aicss-bg-subtle);
}
.csw-pill.is-active {
  border-color: var(--aicss-accent);
  background: var(--aicss-accent-soft);
  color: var(--aicss-accent-text);
  font-weight: 600;
  box-shadow: 0 0 0 1px color-mix(in srgb, var(--aicss-accent) 45%, transparent) inset;
}
.csw-pill:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.csw-pill-sm {
  height: 28px;
  padding: 0 11px;
}
.csw-pill-mini {
  height: 26px;
  padding: 0 10px;
  font-size: 11px;
}

/* ---------- 数字步进输入（a-input-number 替代） ---------- */
.csw-num-wrap {
  display: inline-flex;
  align-items: center;
  height: 34px;
  flex-shrink: 0;
  border: 1px solid var(--aicss-border);
  border-radius: var(--aicss-radius-sm);
  background: var(--aicss-surface);
  overflow: hidden;
  transition:
    border-color 0.2s ease,
    box-shadow 0.2s ease;
}
.csw-num-wrap:focus-within {
  border-color: var(--aicss-accent);
  box-shadow: 0 0 0 3px var(--aicss-accent-soft);
}
.csw-num-sm {
  height: 32px;
}
.csw-num-wrap:has(.csw-num-input:disabled) {
  opacity: 0.55;
}
.csw-step-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 100%;
  padding: 0;
  border: none;
  background: transparent;
  color: var(--aicss-subtle);
  font-size: 14px;
  font-family: inherit;
  cursor: pointer;
  transition:
    background 0.2s ease,
    color 0.2s ease;
}
.csw-step-btn:hover:not(:disabled) {
  background: var(--aicss-accent-soft);
  color: var(--aicss-accent-text);
}
.csw-step-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}
.csw-num-input {
  width: 40px;
  height: 100%;
  padding: 0 2px;
  border: none;
  background: transparent;
  color: var(--aicss-text);
  font-family: inherit;
  font-size: 13px;
  font-weight: 600;
  text-align: center;
  outline: none;
  box-sizing: border-box;
}
.csw-num-sm .csw-num-input {
  width: 36px;
  font-size: 12px;
}
.csw-num-input:disabled {
  opacity: 0.7;
}

/* ---------- 时间 / 下拉 ---------- */
.csw-time-input {
  width: 118px;
  height: 34px;
  padding: 0 10px;
  border: 1px solid var(--aicss-border);
  border-radius: var(--aicss-radius-sm);
  background: var(--aicss-surface);
  color: var(--aicss-text);
  font-family: inherit;
  font-size: 13px;
  box-sizing: border-box;
  outline: none;
  transition:
    border-color 0.2s ease,
    box-shadow 0.2s ease;
}
.csw-time-input:focus {
  border-color: var(--aicss-accent);
  box-shadow: 0 0 0 3px var(--aicss-accent-soft);
}
.csw-select {
  height: 34px;
  padding: 0 28px 0 12px;
  border: 1px solid var(--aicss-border);
  border-radius: var(--aicss-radius-sm);
  background: var(--aicss-surface);
  color: var(--aicss-text);
  font-family: inherit;
  font-size: 13px;
  outline: none;
  cursor: pointer;
  box-sizing: border-box;
  appearance: none;
  -webkit-appearance: none;
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 24 24' fill='none' stroke='%23a64b74' stroke-width='2.4' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpolyline points='6 9 12 15 18 9'%3E%3C/polyline%3E%3C/svg%3E");
  background-repeat: no-repeat;
  background-position: right 9px center;
  transition:
    border-color 0.2s ease,
    box-shadow 0.2s ease;
}
.csw-select:hover {
  border-color: var(--aicss-border-strong);
}
.csw-select:focus {
  border-color: var(--aicss-accent);
  box-shadow: 0 0 0 3px var(--aicss-accent-soft);
}
.csw-select-sm {
  height: 32px;
  min-width: 108px;
  font-size: 12px;
}
.csw-select-lg {
  width: 100%;
  height: 40px;
  font-size: 13px;
}
.csw-select-box {
  position: relative;
}
.csw-select-ico {
  position: absolute;
  left: 12px;
  top: 50%;
  transform: translateY(-50%);
  color: var(--aicss-muted);
  font-size: 14px;
  pointer-events: none;
  z-index: 1;
}
.csw-select-ico svg,
.csw-select-ico :deep(svg) {
  width: 14px;
  height: 14px;
}
.csw-select-box .csw-select-lg {
  padding-left: 36px;
}
.csw-app-state {
  margin-top: 10px;
}
.csw-app-state svg,
.csw-app-state :deep(svg) {
  color: var(--aicss-accent-text);
}
.csw-app-state.is-bound svg,
.csw-app-state.is-bound :deep(svg) {
  color: var(--aicss-accent);
}

/* ---------- 高级设置折叠（原生 details/summary） ---------- */
.csw-adv {
  margin-top: 14px;
  border: 1px solid var(--aicss-border);
  border-radius: var(--aicss-radius);
  background: var(--aicss-surface);
  overflow: hidden;
}
.csw-adv-head {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 13px 16px;
  list-style: none;
  cursor: pointer;
  user-select: none;
  transition: background 0.2s ease;
}
.csw-adv-head::-webkit-details-marker {
  display: none;
}
.csw-adv-head:hover {
  background: var(--aicss-bg-subtle);
}
.csw-adv-ico {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  flex-shrink: 0;
  border-radius: 50%;
  background: var(--aicss-surface-2);
  color: var(--aicss-accent-text);
  font-size: 13px;
}
.csw-adv-ico svg,
.csw-adv-ico :deep(svg) {
  width: 13px;
  height: 13px;
}
.csw-adv-title {
  flex: 1 1 auto;
  font-size: 13px;
  font-weight: 600;
  color: var(--aicss-text);
}
.csw-adv-chevron {
  display: inline-flex;
  align-items: center;
  color: var(--aicss-muted);
  font-size: 12px;
  transition: transform 0.25s ease;
}
.csw-adv-chevron svg,
.csw-adv-chevron :deep(svg) {
  width: 12px;
  height: 12px;
}
.csw-adv[open] .csw-adv-chevron {
  transform: rotate(180deg);
}
.csw-adv-body {
  padding: 0 16px 16px;
}
.csw-adv-sec {
  margin-top: 14px;
}
.csw-interval-box {
  padding: 14px;
  border: 1px solid color-mix(in srgb, var(--aicss-accent) 16%, var(--aicss-border));
  border-radius: var(--aicss-radius);
  background: color-mix(in srgb, var(--aicss-accent) 5%, var(--aicss-surface));
}
.csw-interval-box .csw-label {
  margin-bottom: 10px;
}

/* ---------- cron 公式区 ---------- */
.csw-cron-grid {
  display: grid;
  grid-template-columns: repeat(6, minmax(0, 1fr));
  gap: 8px;
  margin-top: 8px;
}
.csw-cron-input {
  padding: 0 6px;
  text-align: center;
}
.csw-cron-fields {
  margin-top: 4px;
  text-align: center;
  font-size: 11px;
  color: var(--aicss-muted);
}
.csw-mono-chip {
  display: inline-flex;
  align-items: center;
  flex-shrink: 0;
  padding: 5px 10px;
  border: 1px solid color-mix(in srgb, var(--aicss-accent) 25%, var(--aicss-border));
  border-radius: var(--aicss-radius-sm);
  background: var(--aicss-accent-soft);
  color: var(--aicss-accent-text);
  font-family: var(--aicss-font-mono, ui-monospace, SFMono-Regular, Consolas, monospace);
  font-size: 12px;
  line-height: 1.4;
  overflow-wrap: anywhere;
}

/* ---------- 响应式：步骤条折行 / cron 三段换行 ---------- */
@media (max-width: 640px) {
  .csw-head {
    padding: 16px 18px 12px;
  }
  .csw-steps {
    padding: 16px 18px 4px;
  }
  .csw-step-pane {
    padding: 14px 14px 18px;
  }
  .csw-subtitle {
    display: none;
  }
  .csw-step-desc {
    display: none;
  }
  .csw-step-line {
    margin: 0 6px;
  }
  .csw-foot {
    justify-content: center;
  }
  .csw-cron-grid {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
}
</style>

<!-- ============================================================
     非 scoped：Arco Modal 经 Teleport 渲染到 body，scoped 选择器无法命中
     外壳。用 modal-class="create-schedule-wizard" 精准限定，只影响本弹窗。
     ============================================================ -->
<style>
.create-schedule-wizard {
  border-radius: var(--aicss-radius-lg);
  background: var(--aicss-surface);
  overflow: hidden;
}
.create-schedule-wizard .arco-modal-content {
  padding: 0;
  max-height: 92vh;
  display: flex;
  flex-direction: column;
}
.create-schedule-wizard .csw-step-pane {
  max-height: 68vh;
  overflow-y: auto;
}
.create-schedule-wizard .csw-steps {
  flex-shrink: 0;
}
.create-schedule-wizard .csw-head {
  flex-shrink: 0;
}
@media (max-width: 640px) {
  .create-schedule-wizard .csw-step-pane {
    max-height: 78vh;
  }
}
</style>

