<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import io, { Socket } from 'socket.io-client'
import { socketConnectionUrl, socketPath } from '@/config'
import { useCredentialStore } from '@/stores/credential'
import { getCredentialAccessToken } from '@/utils/auth'

type DockState =
  | 'idle'
  | 'connecting'
  | 'listening'
  | 'transcribing'
  | 'thinking'
  | 'speaking'
  | 'paused'
  | 'error'

type VoiceServerEvent =
  | { event: 'rt.state'; data: Record<string, unknown> }
  | { event: 'rt.transcript'; data: Record<string, unknown> }
  | { event: 'rt.agent'; data: Record<string, unknown> }
  | { event: 'rt.stream'; data: Record<string, unknown> }
  | { event: 'rt.audio'; data: Record<string, unknown> }
  | { event: 'rt.control'; data: Record<string, unknown> }
  | { event: 'rt.error'; data: Record<string, unknown> }
  | { event: 'rt.turn-complete'; data: Record<string, unknown> }

const props = withDefaults(
  defineProps<{
    active?: boolean
  }>(),
  {
    active: false,
  },
)

const emit = defineEmits<{
  (e: 'update:active', value: boolean): void
  (e: 'error', error: unknown): void
  (e: 'turn-start', text: string): void
  (e: 'stream-event', payload: { event: string; data: Record<string, unknown> }): void
  (e: 'turn-complete'): void
}>()

const { t } = useI18n()
const credentialStore = useCredentialStore()
const accessToken = computed(() => getCredentialAccessToken(credentialStore.credential))

const enabled = ref(props.active)
const state = ref<DockState>('idle')
const level = ref(0)

let socket: Socket | null = null
let stream: MediaStream | null = null
let audioContext: AudioContext | null = null
let processor: ScriptProcessorNode | null = null
let audioElement: HTMLAudioElement | null = null
let speechActive = false
let lastVoiceAt = 0
let destroyed = false
let playbackQueue: { blob: Blob; sentence: string }[] = []
let playing = false

const statusKey = computed(() => {
  const key = `home.messages.voiceDock${state.value[0].toUpperCase()}${state.value.slice(1)}`
  return key
})

const barStyle = (index: number) => {
  return {
    height: `${Math.max(8, 18 + level.value * 46 + (index === 2 ? 4 : 0))}%`,
    animationDelay: `${index * 0.12}s`,
  }
}

const resetAudioPipeline = () => {
  stopPlayback()
}

const stopPlayback = () => {
  if (audioElement) {
    audioElement.pause()
    audioElement.removeAttribute('src')
    audioElement = null
  }
  playbackQueue = []
  playing = false
}

const playSentence = (audioBase64: string, sentence: string) => {
  if (!audioBase64 || destroyed) return
  try {
    const binary = atob(audioBase64)
    const bytes = new Uint8Array(binary.length)
    for (let i = 0; i < binary.length; i += 1) {
      bytes[i] = binary.charCodeAt(i)
    }
    const blob = new Blob([bytes as unknown as BlobPart], { type: 'audio/mpeg' })
    playbackQueue.push({ blob, sentence })
    void pumpPlayback()
  } catch {
    // ignore malformed audio frame
  }
}

const pumpPlayback = async () => {
  if (playing || destroyed) return
  const item = playbackQueue.shift()
  if (!item) return
  playing = true
  const audio = new Audio()
  audioElement = audio
  audio.src = URL.createObjectURL(item.blob)
  audio.onended = () => {
    URL.revokeObjectURL(audio.src)
    playing = false
    void pumpPlayback()
  }
  audio.onerror = () => {
    URL.revokeObjectURL(audio.src)
    playing = false
    void pumpPlayback()
  }
  try {
    await audio.play()
  } catch {
    playing = false
    void pumpPlayback()
  }
}

const setState = (value: DockState) => {
  state.value = value
}

const emitBarge = () => {
  if (!socket?.connected || !enabled.value) return
  stopPlayback()
  socket.emit('rt.barge')
}

const handleServerEvent = (payload: VoiceServerEvent) => {
  const event = payload.event
  const data = payload.data || {}
  if (event === 'rt.state') {
    const serverState = String(data.state || '')
    if (serverState === 'listening') setState('listening')
    else if (serverState === 'transcribing') setState('transcribing')
    else if (serverState === 'thinking') setState('thinking')
    else if (serverState === 'speaking') setState('speaking')
    else if (serverState === 'paused') setState('paused')
  } else if (event === 'rt.transcript') {
    if (data.final) {
      setState('thinking')
      emit('turn-start', String(data.text || ''))
    }
  } else if (event === 'rt.stream') {
    emit('stream-event', {
      event: String((data as { event?: string }).event || ''),
      data: ((data as { data?: Record<string, unknown> }).data || {}) as Record<string, unknown>,
    })
  } else if (event === 'rt.audio') {
    setState('speaking')
    playSentence(String(data.audio || ''), String(data.sentence || ''))
  } else if (event === 'rt.control') {
    stopPlayback()
    setState('listening')
  } else if (event === 'rt.error') {
    setState('error')
    emit('error', new Error(String(data.message || 'voice session error')))
  } else if (event === 'rt.turn-complete') {
    emit('turn-complete')
  }
}

const connectSocket = () => {
  if (socket || destroyed || !enabled.value) return
  setState('connecting')
  socket = io(`${socketConnectionUrl}/rt-voice`, {
    auth: (callback) => {
      callback({ token: accessToken.value })
    },
    path: socketPath,
    transports: ['websocket'],
    reconnection: true,
    reconnectionDelay: 1000,
    reconnectionDelayMax: 5000,
    reconnectionAttempts: 5,
  })
  socket.on('connect', () => {
    if (!socket) return
    socket.emit('rt.start', { sample_rate: audioContext?.sampleRate || 16000 })
  })
  socket.on('rt.state', (data) => handleServerEvent({ event: 'rt.state', data }))
  socket.on('rt.transcript', (data) => handleServerEvent({ event: 'rt.transcript', data }))
  socket.on('rt.stream', (data) => handleServerEvent({ event: 'rt.stream', data }))
  socket.on('rt.audio', (data) => handleServerEvent({ event: 'rt.audio', data }))
  socket.on('rt.control', (data) => handleServerEvent({ event: 'rt.control', data }))
  socket.on('rt.error', (data) => handleServerEvent({ event: 'rt.error', data }))
  socket.on('disconnect', () => {
    if (enabled.value && !destroyed) setState('error')
  })
  socket.on('connect_error', (error) => {
    setState('error')
    emit('error', error)
  })
}

const disconnectSocket = () => {
  if (!socket) return
  socket.off()
  socket.disconnect()
  socket = null
}

const startCapture = async () => {
  if (destroyed || !enabled.value) return
  const AudioContextClass = window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext
  if (!audioContext) audioContext = new AudioContextClass()
  if (audioContext.state === 'suspended') {
    try {
      await audioContext.resume()
    } catch {
      // 浏览器仍可能要求再次用户手势，稍后通过点击触发恢复
    }
  }
  try {
    stream = await navigator.mediaDevices.getUserMedia({ audio: true })
  } catch (error) {
    setState('error')
    emit('error', error)
    return
  }
  if (audioContext.state === 'suspended') {
    try {
      await audioContext.resume()
    } catch {
      // 麦克风授权后仍未恢复时保持采集，等待页面手势
    }
  }

  const source = audioContext.createMediaStreamSource(stream)

  processor = audioContext.createScriptProcessor(2048, 1, 1)
  source.connect(processor)
  const muteSink = audioContext.createGain()
  muteSink.gain.value = 0
  processor.connect(muteSink)
  muteSink.connect(audioContext.destination)
  processor.onaudioprocess = (event) => {
    if (!enabled.value || destroyed) return
    const input = event.inputBuffer.getChannelData(0)
    const pcm = new Int16Array(input.length)
    let sumSquares = 0
    for (let i = 0; i < input.length; i += 1) {
      const sample = Math.max(-1, Math.min(1, input[i]))
      pcm[i] = sample < 0 ? sample * 0x8000 : sample * 0x7fff
      sumSquares += sample * sample
    }
    const rms = Math.sqrt(sumSquares / input.length) * 32768
    level.value = Math.max(0, Math.min(1, rms / 16000))

    const now = Date.now()
    if (rms >= 900) {
      if (playing) emitBarge()
      speechActive = true
      lastVoiceAt = now
    } else if (speechActive && now - lastVoiceAt > 4000) {
      speechActive = false
    }

    if (socket?.connected) {
      const buffer = pcm.buffer.slice(0)
      socket.emit('rt.audio', buffer)
    }
  }
  setState('listening')
}

const stopCapture = () => {
  if (processor) {
    processor.disconnect()
    processor.onaudioprocess = null
    processor = null
  }
  if (audioContext && audioContext.state !== 'closed') {
    void audioContext.close()
  }
  audioContext = null
  if (stream) {
    stream.getTracks().forEach((track) => track.stop())
    stream = null
  }
  resetAudioPipeline()
}

const start = async () => {
  const AudioContextClass = window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext
  if (!audioContext) audioContext = new AudioContextClass()
  if (audioContext.state === 'suspended') {
    try {
      await audioContext.resume()
    } catch {
      // 忽略；startCapture 里会再次尝试
    }
  }
  connectSocket()
  await startCapture()
}

const cancel = () => {
  stopCapture()
  if (socket?.connected) socket.emit('rt.stop')
  disconnectSocket()
  speechActive = false
  setState('idle')
}

const handleStop = () => {
  stopPlayback()
  if (socket?.connected) socket.emit('rt.stop')
  speechActive = false
  setState('paused')
}

const handleResume = () => {
  if (socket?.connected) socket.emit('rt.resume')
  setState('listening')
}

const handlePauseResume = () => {
  if (state.value === 'paused') {
    handleResume()
  } else {
    handleStop()
  }
}

const toggle = async () => {
  const next = !enabled.value
  enabled.value = next
  emit('update:active', next)
  if (next) {
    await start()
  } else {
    await cancel()
  }
}

watch(
  () => props.active,
  (value) => {
    if (value === enabled.value) return
    enabled.value = value
    if (value) {
      void start()
    } else {
      void cancel()
    }
  },
)

onUnmounted(() => {
  destroyed = true
  void cancel()
})

defineExpose({
  start,
  cancel,
  stopListening: () => {
    stopPlayback()
  },
  resumeListening: () => {
    setState('listening')
  },
})
</script>

<template>
  <div class="voice-dock" :class="{ 'voice-dock--active': enabled }">
    <div class="voice-dock__header">
      <button
        type="button"
        class="voice-dock__toggle"
        :aria-pressed="enabled"
        :title="enabled ? t('home.messages.voiceDockToggleOff') : t('home.messages.voiceDockToggleOn')"
        @click="toggle"
      >
        <svg v-if="!enabled" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <rect x="9" y="3" width="6" height="11" rx="3" stroke-width="1.8" />
          <path
            stroke-linecap="round"
            stroke-linejoin="round"
            stroke-width="1.8"
            d="M6 10.5v1a6 6 0 0 0 12 0v-1M12 17.5V21M8.5 21h7"
          />
        </svg>
        <svg v-else fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path
            stroke-linecap="round"
            stroke-linejoin="round"
            stroke-width="1.8"
            d="M3 3l18 18M9 5.5A3.5 3.5 0 0 1 12.5 2H15a3 3 0 0 1 3 3v5.2M6.5 9.8V11a6 6 0 0 0 9.3 4.9M12 17.5V21M8.5 21h7"
          />
        </svg>
      </button>

      <div class="voice-dock__status">
        <span class="voice-dock__dot" :class="`voice-dock__dot--${state}`" />
        <span class="voice-dock__status-text">{{ t(statusKey) }}</span>
      </div>

      <button
        v-if="enabled"
        type="button"
        class="voice-dock__stop"
        :title="state === 'paused' ? t('home.messages.voiceDockResume') : t('home.messages.voiceDockPause')"
        @click="handlePauseResume"
      >
        <svg v-if="state === 'paused'" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M7 5.5v13l11-6.5z" />
        </svg>
        <svg v-else viewBox="0 0 24 24" fill="currentColor">
          <path d="M6 6h12v12H6z" />
        </svg>
      </button>
    </div>

    <div class="voice-dock__visual" :class="{ 'is-active': state === 'listening' }">
      <span
        v-for="index in 5"
        :key="index"
        class="voice-dock__bar"
        :class="{ 'is-listening': state === 'listening' }"
        :style="barStyle(index)"
      />
    </div>

  </div>
</template>

<style scoped>
.voice-dock {
  min-width: 0;
  border: 1px solid var(--aicss-border-strong);
  border-radius: 14px;
  background: var(--aicss-surface);
  box-shadow: var(--aicss-shadow-card);
  padding: 10px 12px 12px;
  display: flex;
  flex-direction: column;
  gap: 10px;
  transition:
    border-color 0.3s ease,
    box-shadow 0.3s ease,
    background 0.3s ease;
}

.voice-dock--active {
  border-color: color-mix(in srgb, var(--aicss-accent) 52%, var(--aicss-border-strong));
  box-shadow:
    0 0 0 4px color-mix(in srgb, var(--aicss-accent) 8%, transparent),
    var(--aicss-shadow-elevated);
}

.voice-dock__header {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.voice-dock__toggle,
.voice-dock__stop {
  width: 32px;
  height: 32px;
  flex: 0 0 auto;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 10px;
  border: 1px solid var(--aicss-border);
  background: var(--aicss-surface-2);
  color: var(--aicss-muted);
  transition:
    color 0.2s ease,
    background 0.2s ease,
    border-color 0.2s ease;
}

.voice-dock__toggle svg,
.voice-dock__stop svg {
  width: 17px;
  height: 17px;
}

.voice-dock__toggle:hover,
.voice-dock--active .voice-dock__toggle {
  color: var(--aicss-accent);
  border-color: color-mix(in srgb, var(--aicss-accent) 40%, var(--aicss-border));
}

.voice-dock__stop {
  color: var(--aicss-danger);
  border-color: color-mix(in srgb, var(--aicss-danger) 30%, var(--aicss-border));
}

.voice-dock__status {
  min-width: 0;
  flex: 1 1 auto;
  display: flex;
  align-items: center;
  gap: 6px;
}

.voice-dock__dot {
  width: 8px;
  height: 8px;
  flex: 0 0 auto;
  border-radius: 50%;
  background: var(--aicss-muted);
}

.voice-dock__dot--listening,
.voice-dock__dot--transcribing,
.voice-dock__dot--thinking,
.voice-dock__dot--speaking {
  background: var(--aicss-accent);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--aicss-accent) 18%, transparent);
}

.voice-dock__dot--error {
  background: var(--aicss-danger);
}

.voice-dock__dot--paused,
.voice-dock__dot--connecting,
.voice-dock__dot--idle {
  background: var(--aicss-muted);
}

.voice-dock__status-text {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--aicss-muted);
  font-size: 12px;
}

.voice-dock__visual {
  height: 38px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
}

.voice-dock__bar {
  width: 4px;
  border-radius: 4px;
  background: color-mix(in srgb, var(--aicss-accent) 34%, var(--aicss-border));
  transition: height 0.2s ease;
}

.voice-dock__bar.is-listening {
  animation: voice-dock-breathe 1s ease-in-out infinite;
}

.voice-dock__transcript {
  max-height: 64px;
  overflow: hidden;
  display: -webkit-box;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 3;
  margin: 0;
  color: var(--aicss-muted);
  font-size: 12px;
  line-height: 1.5;
  word-break: break-word;
}

@keyframes voice-dock-breathe {
  0%,
  100% {
    transform: scaleY(0.55);
  }
  50% {
    transform: scaleY(1);
  }
}
</style>
