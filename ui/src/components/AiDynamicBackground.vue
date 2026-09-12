<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'

interface Props {
  className?: string
  intensity?: 'low' | 'medium' | 'high'
  showParticles?: boolean
  showGrid?: boolean
}

interface Particle {
  x: number
  y: number
  vx: number
  vy: number
  radius: number
  alpha: number
  pulse: number
  color: string
}

const props = withDefaults(defineProps<Props>(), {
  className: '',
  intensity: 'medium',
  showParticles: true,
  showGrid: true,
})

const INTENSITY_CONFIG = {
  low: {
    auroraOpacity: 0.74,
    glowOpacity: 0.72,
    gridOpacity: 0.12,
    beamOpacity: 0.1,
    noiseOpacity: 0.04,
    blobBlur: 88,
    particleAlpha: 0.42,
    particleCount: 8,
    particleSpeed: 4.5,
  },
  medium: {
    auroraOpacity: 0.84,
    glowOpacity: 0.82,
    gridOpacity: 0.15,
    beamOpacity: 0.13,
    noiseOpacity: 0.05,
    blobBlur: 104,
    particleAlpha: 0.52,
    particleCount: 12,
    particleSpeed: 5.4,
  },
  high: {
    auroraOpacity: 0.94,
    glowOpacity: 0.92,
    gridOpacity: 0.18,
    beamOpacity: 0.16,
    noiseOpacity: 0.06,
    blobBlur: 118,
    particleAlpha: 0.64,
    particleCount: 16,
    particleSpeed: 6.2,
  },
} as const

const auroraStreams = [
  {
    id: 'stream-a',
    className: '-left-[22%] top-[0%] h-[18rem] w-[145%] sm:h-[22rem] lg:h-[28rem]',
    motionClass: 'stream-flow-a',
    toneClass: 'aurora-stream--a',
  },
  {
    id: 'stream-b',
    className: '-right-[20%] top-[18%] h-[17rem] w-[138%] sm:h-[21rem] lg:h-[26rem]',
    motionClass: 'stream-flow-b',
    toneClass: 'aurora-stream--b',
  },
  {
    id: 'stream-c',
    className: '-left-[10%] bottom-[2%] h-[15rem] w-[126%] sm:h-[18rem] lg:h-[22rem]',
    motionClass: 'stream-flow-c',
    toneClass: 'aurora-stream--c',
  },
  {
    id: 'stream-d',
    className: 'left-[-12%] top-[36%] h-[13rem] w-[118%] sm:h-[16rem] lg:h-[20rem]',
    motionClass: 'stream-flow-d',
    toneClass: 'aurora-stream--d',
  },
]

const beams = [
  { id: 'beam-a', className: 'beam-a top-[18%]' },
  { id: 'beam-b', className: 'beam-b top-[48%]' },
  { id: 'beam-c', className: 'beam-c top-[74%]' },
]

// 兜底调色板（SSR / 取色失败时使用），RGB 三元组字符串
const FALLBACK_PALETTE = ['233, 30, 99', '214, 51, 132', '255, 158, 197', '201, 136, 166']

const hexToRgbTriplet = (value: string): string | null => {
  const normalized = value.trim().replace('#', '')
  const full =
    normalized.length === 3
      ? normalized
          .split('')
          .map((char) => char + char)
          .join('')
      : normalized
  if (!/^[0-9a-fA-F]{6}$/.test(full)) return null
  const int = Number.parseInt(full, 16)
  const r = (int >> 16) & 255
  const g = (int >> 8) & 255
  const b = int & 255
  return `${r}, ${g}, ${b}`
}

const readThemeVar = (name: string, fallback: string) => {
  if (typeof window === 'undefined') return fallback
  const raw = getComputedStyle(document.documentElement).getPropertyValue(name)
  return hexToRgbTriplet(raw) || fallback
}

/** 从主题令牌推导粒子调色板，随浅/深主题自动切换 */
const resolveThemePalette = (): string[] => {
  const accent = readThemeVar('--aicss-accent', FALLBACK_PALETTE[0])
  const violet = readThemeVar('--aicss-violet', FALLBACK_PALETTE[1])
  const subtle = readThemeVar('--aicss-subtle', FALLBACK_PALETTE[3])
  return [accent, violet, accent, subtle, violet]
}

const rootRef = ref<HTMLDivElement | null>(null)
const canvasRef = ref<HTMLCanvasElement | null>(null)

const intensityConfig = computed(() => INTENSITY_CONFIG[props.intensity])

const backgroundStyle = computed<Record<string, string>>(() => ({
  '--aurora-opacity': String(intensityConfig.value.auroraOpacity),
  '--glow-opacity': String(intensityConfig.value.glowOpacity),
  '--grid-opacity': String(intensityConfig.value.gridOpacity),
  '--beam-opacity': String(intensityConfig.value.beamOpacity),
  '--noise-opacity': String(intensityConfig.value.noiseOpacity),
  '--blob-blur': `${intensityConfig.value.blobBlur}px`,
  '--particle-alpha': String(intensityConfig.value.particleAlpha),
}))

let resizeObserver: ResizeObserver | null = null
let animationFrameId: number | null = null
let particles: Particle[] = []
let viewportWidth = 0
let viewportHeight = 0
let devicePixelRatioValue = 1
let lastFrameTime = 0
let themeObserver: MutationObserver | null = null

const initParticles = (width: number, height: number) => {
  const palette = resolveThemePalette()
  particles = Array.from({ length: intensityConfig.value.particleCount }, () => {
    const speed = intensityConfig.value.particleSpeed
    const baseDirectionX = (Math.random() - 0.5) * speed
    const baseDirectionY = (Math.random() - 0.5) * speed * 0.7

    return {
      x: Math.random() * width,
      y: Math.random() * height,
      vx: baseDirectionX,
      vy: baseDirectionY,
      radius: Math.random() * 1.6 + 0.7,
      alpha: Math.random() * 0.18 + 0.1,
      pulse: Math.random() * Math.PI * 2,
      color: palette[Math.floor(Math.random() * palette.length)],
    }
  })
}

const syncCanvasSize = () => {
  const root = rootRef.value
  const canvas = canvasRef.value
  if (!root || !canvas) return

  const rect = root.getBoundingClientRect()
  viewportWidth = Math.max(rect.width, 1)
  viewportHeight = Math.max(rect.height, 1)
  devicePixelRatioValue = Math.min(window.devicePixelRatio || 1, 2)

  canvas.width = Math.max(1, Math.floor(viewportWidth * devicePixelRatioValue))
  canvas.height = Math.max(1, Math.floor(viewportHeight * devicePixelRatioValue))
  canvas.style.width = `${viewportWidth}px`
  canvas.style.height = `${viewportHeight}px`

  const ctx = canvas.getContext('2d')
  if (!ctx) return

  ctx.setTransform(devicePixelRatioValue, 0, 0, devicePixelRatioValue, 0, 0)
  initParticles(viewportWidth, viewportHeight)
}

const stopAnimation = () => {
  if (animationFrameId !== null) {
    cancelAnimationFrame(animationFrameId)
    animationFrameId = null
  }
}

const renderParticles = (timestamp: number) => {
  const canvas = canvasRef.value
  if (!canvas || !props.showParticles) {
    stopAnimation()
    return
  }

  const ctx = canvas.getContext('2d')
  if (!ctx) {
    stopAnimation()
    return
  }

  if (!lastFrameTime) {
    lastFrameTime = timestamp
  }

  const deltaSeconds = Math.min((timestamp - lastFrameTime) / 1000, 0.05)
  lastFrameTime = timestamp

  ctx.clearRect(0, 0, viewportWidth, viewportHeight)
  ctx.save()

  particles.forEach((particle) => {
    particle.x += particle.vx * deltaSeconds
    particle.y += particle.vy * deltaSeconds

    if (particle.x < -24) particle.x = viewportWidth + 24
    if (particle.x > viewportWidth + 24) particle.x = -24
    if (particle.y < -24) particle.y = viewportHeight + 24
    if (particle.y > viewportHeight + 24) particle.y = -24

    const pulseAlpha =
      (particle.alpha + (Math.sin(timestamp * 0.00045 + particle.pulse) + 1) * 0.05) *
      intensityConfig.value.particleAlpha

    const glow = ctx.createRadialGradient(
      particle.x,
      particle.y,
      0,
      particle.x,
      particle.y,
      particle.radius * 5,
    )

    glow.addColorStop(0, `rgba(${particle.color}, ${pulseAlpha})`)
    glow.addColorStop(0.38, `rgba(${particle.color}, ${pulseAlpha * 0.42})`)
    glow.addColorStop(1, `rgba(${particle.color}, 0)`)

    ctx.fillStyle = glow
    ctx.beginPath()
    ctx.arc(particle.x, particle.y, particle.radius * 5, 0, Math.PI * 2)
    ctx.fill()
  })

  ctx.restore()
  animationFrameId = requestAnimationFrame(renderParticles)
}

const startAnimation = async () => {
  if (!props.showParticles) return

  await nextTick()
  syncCanvasSize()
  stopAnimation()
  lastFrameTime = 0
  animationFrameId = requestAnimationFrame(renderParticles)
}

onMounted(async () => {
  await nextTick()

  if (typeof ResizeObserver !== 'undefined' && rootRef.value) {
    resizeObserver = new ResizeObserver(() => {
      syncCanvasSize()
    })
    resizeObserver.observe(rootRef.value)
  } else {
    window.addEventListener('resize', syncCanvasSize)
  }

  // 监听主题切换，让粒子调色板随之更新
  if (typeof MutationObserver !== 'undefined' && typeof document !== 'undefined') {
    themeObserver = new MutationObserver(() => {
      if (particles.length > 0) {
        const palette = resolveThemePalette()
        particles.forEach((particle) => {
          particle.color = palette[Math.floor(Math.random() * palette.length)]
        })
      }
    })
    themeObserver.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ['data-theme'],
    })
  }

  startAnimation()
})

watch(
  () => props.showParticles,
  async (enabled) => {
    if (!enabled) {
      stopAnimation()
      return
    }

    await startAnimation()
  },
)

watch(
  () => props.intensity,
  async () => {
    if (!props.showParticles) return
    await startAnimation()
  },
)

onUnmounted(() => {
  stopAnimation()
  resizeObserver?.disconnect()
  themeObserver?.disconnect()
  themeObserver = null
  if (!resizeObserver) {
    window.removeEventListener('resize', syncCanvasSize)
  }
})
</script>

<template>
  <div
    ref="rootRef"
    :class="[
      'ai-dynamic-background absolute inset-0 isolate overflow-hidden rounded-[inherit] bg-[var(--aicss-bg)] pointer-events-none',
      className,
    ]"
    :style="backgroundStyle"
    aria-hidden="true"
  >
    <div class="ai-veil-top absolute inset-0" />

    <div class="aurora-base absolute inset-[-12%]" />

    <div class="absolute inset-0 overflow-hidden">
      <div
        v-for="stream in auroraStreams"
        :key="stream.id"
        :class="[
          'aurora-stream absolute rounded-[999px]',
          stream.className,
          stream.motionClass,
          stream.toneClass,
        ]"
      />
    </div>

    <div class="soft-glow-layer absolute inset-0" />

    <div v-if="showGrid" class="grid-layer absolute inset-0" />

    <div v-if="showGrid" class="beam-layer absolute inset-0">
      <span
        v-for="beam in beams"
        :key="beam.id"
        :class="['beam absolute left-1/2 block', beam.className]"
      />
    </div>

    <canvas
      v-show="showParticles"
      ref="canvasRef"
      class="particle-layer absolute inset-0 h-full w-full"
      style="display: block"
    />

    <div class="noise-layer absolute inset-0" />

    <div class="ai-veil-final absolute inset-0" />
  </div>
</template>

<style scoped>
.ai-dynamic-background {
  contain: layout paint style;
  transform: translateZ(0);
  background: var(--aicss-bg);
}

.ai-veil-top {
  background: linear-gradient(
    180deg,
    color-mix(in srgb, var(--aicss-surface) 78%, transparent) 0%,
    color-mix(in srgb, var(--aicss-bg) 66%, transparent) 36%,
    color-mix(in srgb, var(--aicss-surface) 72%, transparent) 100%
  );
}

.aurora-base {
  opacity: var(--aurora-opacity);
  background:
    radial-gradient(
      circle at 16% 18%,
      color-mix(in srgb, var(--aicss-accent) 22%, transparent),
      transparent 28%
    ),
    radial-gradient(
      circle at 84% 16%,
      color-mix(in srgb, var(--aicss-violet) 20%, transparent),
      transparent 26%
    ),
    radial-gradient(
      circle at 58% 74%,
      color-mix(in srgb, var(--aicss-accent) 16%, transparent),
      transparent 28%
    ),
    linear-gradient(
      120deg,
      var(--aicss-bg) 0%,
      var(--aicss-surface-2) 26%,
      var(--aicss-surface-3) 46%,
      var(--aicss-surface-2) 68%,
      var(--aicss-bg) 100%
    );
  background-size: 160% 160%;
  animation: aurora-pan 20s ease-in-out infinite alternate;
}

.aurora-stream {
  filter: blur(var(--blob-blur));
  opacity: calc(var(--aurora-opacity) * 0.9);
  will-change: transform, opacity;
  transform-origin: center;
}

.aurora-stream--a {
  background: linear-gradient(
    100deg,
    transparent 8%,
    color-mix(in srgb, var(--aicss-accent) 30%, transparent) 24%,
    color-mix(in srgb, var(--aicss-violet) 26%, transparent) 40%,
    color-mix(in srgb, var(--aicss-accent) 24%, transparent) 58%,
    transparent 88%
  );
}

.aurora-stream--b {
  background: linear-gradient(
    105deg,
    transparent 10%,
    color-mix(in srgb, var(--aicss-violet) 28%, transparent) 26%,
    color-mix(in srgb, var(--aicss-accent) 24%, transparent) 42%,
    color-mix(in srgb, var(--aicss-accent-text) 20%, transparent) 58%,
    transparent 88%
  );
}

.aurora-stream--c {
  background: linear-gradient(
    95deg,
    transparent 8%,
    color-mix(in srgb, var(--aicss-subtle) 22%, transparent) 24%,
    color-mix(in srgb, var(--aicss-accent) 24%, transparent) 40%,
    color-mix(in srgb, var(--aicss-violet) 26%, transparent) 58%,
    transparent 88%
  );
}

.aurora-stream--d {
  background: linear-gradient(
    90deg,
    transparent 12%,
    color-mix(in srgb, var(--aicss-violet) 20%, transparent) 28%,
    color-mix(in srgb, var(--aicss-surface) 16%, transparent) 44%,
    color-mix(in srgb, var(--aicss-accent) 22%, transparent) 58%,
    transparent 90%
  );
}

.soft-glow-layer {
  opacity: var(--glow-opacity);
  background:
    radial-gradient(
      circle at 50% 16%,
      color-mix(in srgb, var(--aicss-surface) 62%, transparent),
      transparent 34%
    ),
    radial-gradient(
      circle at 30% 58%,
      color-mix(in srgb, var(--aicss-violet) 18%, transparent),
      transparent 24%
    ),
    radial-gradient(
      circle at 72% 54%,
      color-mix(in srgb, var(--aicss-accent) 16%, transparent),
      transparent 24%
    );
  animation: glow-breathe 14s ease-in-out infinite;
}

.grid-layer {
  opacity: var(--grid-opacity);
  background-image:
    linear-gradient(
      to right,
      color-mix(in srgb, var(--aicss-border-strong) 60%, transparent) 1px,
      transparent 1px
    ),
    linear-gradient(
      to bottom,
      color-mix(in srgb, var(--aicss-border-strong) 44%, transparent) 1px,
      transparent 1px
    );
  background-size: 84px 84px;
  background-position: center center;
  -webkit-mask-image: radial-gradient(circle at center, rgba(0, 0, 0, 0.9) 10%, transparent 78%);
  mask-image: radial-gradient(circle at center, rgba(0, 0, 0, 0.9) 10%, transparent 78%);
}

.grid-layer::before {
  content: '';
  position: absolute;
  inset: -18%;
  background: linear-gradient(
    110deg,
    transparent 40%,
    color-mix(in srgb, var(--aicss-accent) 14%, transparent) 50%,
    transparent 60%
  );
  opacity: 0.7;
  transform: translate3d(-14%, 0, 0);
  animation: grid-scan 20s linear infinite;
}

.beam-layer {
  -webkit-mask-image: radial-gradient(circle at center, rgba(0, 0, 0, 0.8) 10%, transparent 82%);
  mask-image: radial-gradient(circle at center, rgba(0, 0, 0, 0.8) 10%, transparent 82%);
}

.beam {
  width: 140%;
  height: 1px;
  margin-left: -70%;
  opacity: var(--beam-opacity);
  background: linear-gradient(
    90deg,
    transparent 0%,
    color-mix(in srgb, var(--aicss-accent) 18%, transparent) 22%,
    color-mix(in srgb, var(--aicss-violet) 28%, transparent) 50%,
    color-mix(in srgb, var(--aicss-accent) 18%, transparent) 78%,
    transparent 100%
  );
  filter: blur(0.4px);
  transform-origin: center;
}

.beam-a {
  transform: rotate(-12deg);
  animation: beam-float-a 18s ease-in-out infinite;
}

.beam-b {
  transform: rotate(4deg);
  animation: beam-float-b 22s ease-in-out infinite;
}

.beam-c {
  transform: rotate(16deg);
  animation: beam-float-c 20s ease-in-out infinite;
}

.noise-layer {
  opacity: var(--noise-opacity);
  background-image:
    radial-gradient(color-mix(in srgb, var(--aicss-muted) 18%, transparent) 0.55px, transparent 0.7px),
    radial-gradient(color-mix(in srgb, var(--aicss-surface) 88%, transparent) 0.4px, transparent 0.55px);
  background-size: 14px 14px, 18px 18px;
  background-position: 0 0, 8px 10px;
  mix-blend-mode: soft-light;
}

.particle-layer {
  mix-blend-mode: normal;
}

.ai-veil-final {
  background:
    radial-gradient(
      circle at 50% 14%,
      color-mix(in srgb, var(--aicss-surface) 52%, transparent) 0%,
      transparent 62%
    ),
    linear-gradient(
      180deg,
      color-mix(in srgb, var(--aicss-bg) 24%, transparent) 0%,
      transparent 36%,
      color-mix(in srgb, var(--aicss-bg) 20%, transparent) 100%
    );
}

.stream-flow-a {
  animation: stream-flow-a 18s ease-in-out infinite alternate;
}

.stream-flow-b {
  animation: stream-flow-b 22s ease-in-out infinite alternate;
}

.stream-flow-c {
  animation: stream-flow-c 20s ease-in-out infinite alternate;
}

.stream-flow-d {
  animation: stream-flow-d 24s ease-in-out infinite alternate;
}

@keyframes aurora-pan {
  0% {
    transform: translate3d(-2%, -1%, 0) scale(1.02);
    background-position: 0% 50%;
  }

  100% {
    transform: translate3d(2%, 1%, 0) scale(1.06);
    background-position: 100% 50%;
  }
}

@keyframes glow-breathe {
  0%,
  100% {
    opacity: calc(var(--glow-opacity) * 0.92);
    transform: scale(1);
  }

  50% {
    opacity: var(--glow-opacity);
    transform: scale(1.03);
  }
}

@keyframes stream-flow-a {
  0%,
  100% {
    transform: translate3d(-2%, -2%, 0) rotate(-9deg) scaleX(1.04) scaleY(0.96);
  }

  50% {
    transform: translate3d(2%, 2%, 0) rotate(-5deg) scaleX(1.1) scaleY(1.02);
  }
}

@keyframes stream-flow-b {
  0%,
  100% {
    transform: translate3d(2%, -1%, 0) rotate(12deg) scaleX(1.03) scaleY(0.94);
  }

  50% {
    transform: translate3d(-3%, 2%, 0) rotate(7deg) scaleX(1.08) scaleY(1.02);
  }
}

@keyframes stream-flow-c {
  0%,
  100% {
    transform: translate3d(-1%, 0, 0) rotate(7deg) scaleX(1.02) scaleY(0.92);
  }

  50% {
    transform: translate3d(3%, -2%, 0) rotate(3deg) scaleX(1.06) scaleY(1);
  }
}

@keyframes stream-flow-d {
  0%,
  100% {
    transform: translate3d(0, 0, 0) rotate(-5deg) scaleX(1) scaleY(0.9);
  }

  50% {
    transform: translate3d(4%, 1%, 0) rotate(-1deg) scaleX(1.04) scaleY(0.98);
  }
}

@keyframes grid-scan {
  0% {
    transform: translate3d(-10%, 0, 0);
  }

  100% {
    transform: translate3d(10%, 0, 0);
  }
}

@keyframes beam-float-a {
  0%,
  100% {
    transform: translate3d(0, 0, 0) rotate(-12deg);
  }

  50% {
    transform: translate3d(0, 10px, 0) rotate(-10deg);
  }
}

@keyframes beam-float-b {
  0%,
  100% {
    transform: translate3d(0, 0, 0) rotate(4deg);
  }

  50% {
    transform: translate3d(0, -8px, 0) rotate(6deg);
  }
}

@keyframes beam-float-c {
  0%,
  100% {
    transform: translate3d(0, 0, 0) rotate(16deg);
  }

  50% {
    transform: translate3d(0, 12px, 0) rotate(14deg);
  }
}

@media (prefers-reduced-motion: reduce) {
  .aurora-base,
  .aurora-stream,
  .soft-glow-layer,
  .grid-layer::before,
  .beam {
    animation: none !important;
  }
}
</style>
