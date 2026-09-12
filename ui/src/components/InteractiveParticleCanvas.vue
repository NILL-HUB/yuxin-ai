<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue'

const props = withDefaults(
  defineProps<{
    /**
     * 固定粒子数量。传入则按此值渲染（向后兼容旧调用）；
     * 不传则根据画布面积按 particleArea 自适应计算，避免大屏稀疏、小屏过密。
     */
    particleCount?: number
    /**
     * 连线距离。不传时按粒子平均间距自适应推导，
     * 保证不同屏幕密度下连线疏密均衡（过大易糊成蛛网，过小则互相孤立）。
     */
    linkDistance?: number
    particleColor?: string
    mouseLinkColor?: string
    /** 自适应模式的密度基准：每个粒子占据的平均面积（px²），值越小粒子越密 */
    particleArea?: number
    /** 自适应模式的下限，避免极小画布上粒子过少 */
    minParticles?: number
    /** 自适应模式的上限，避免超大画布上粒子过多导致掉帧 */
    maxParticles?: number
  }>(),
  {
    particleColor: '#3b82f6',
    mouseLinkColor: '#0ea5e9',
    particleArea: 8200,
    minParticles: 70,
    maxParticles: 240,
  },
)

type Particle = {
  x: number
  y: number
  // 网格锚点（均匀分布的基准位），粒子围绕它轻微摆动，从根本上避免漂移抱团
  homeX: number
  homeY: number
  // 摆动相位与角速度，让每个粒子的漂浮节奏各不相同
  phase: number
  speed: number
  radius: number
  r: number
}

const canvasRef = ref<HTMLCanvasElement | null>(null)
let context: CanvasRenderingContext2D | null = null
let particles: Particle[] = []
let animationFrame = 0
let prefersReducedMotion = false
let resizeObserver: ResizeObserver | null = null
let resizeFrame = 0
// 逻辑绘制尺寸（CSS 像素），与鼠标坐标同一坐标系
let viewW = 0
let viewH = 0
// 当前生效的连线距离（显式 props.linkDistance 优先，否则按平均间距推导）
let linkDist = 0
const mouse: { x: number | null; y: number | null } = { x: null, y: null }

/** 自适应计算目标粒子数：显式 particleCount 优先，否则按面积推导并夹在下限/上限之间 */
const resolveParticleCount = () => {
  const area = viewW * viewH
  const auto = area > 0 ? Math.round(area / props.particleArea) : props.minParticles
  const raw = props.particleCount ?? auto
  return Math.min(props.maxParticles, Math.max(props.minParticles, raw))
}

/**
 * 解析连线距离：显式传入则直接使用；
 * 否则按粒子平均间距（√(面积/数量)）的约 1.2 倍推导，
 * 只连接正交近邻、不连对角，避免密度升高后糊成实心蛛网。
 */
const resolveLinkDistance = (count: number) => {
  if (props.linkDistance != null) return props.linkDistance
  const area = viewW * viewH
  if (!area || !count) return 100
  const avgSpacing = Math.sqrt(area / count)
  return avgSpacing * 1.2
}

/** 同步画布像素尺寸，并按 devicePixelRatio 缩放绘制上下文，保证高分屏清晰 */
const setupCanvasSize = () => {
  const canvas = canvasRef.value
  if (!canvas || !context) return false

  const width = canvas.clientWidth
  const height = canvas.clientHeight
  if (!width || !height) return false

  const dpr = Math.min(window.devicePixelRatio || 1, 2)
  canvas.width = Math.round(width * dpr)
  canvas.height = Math.round(height * dpr)
  context.setTransform(dpr, 0, 0, dpr, 0, 0)

  viewW = width
  viewH = height
  return true
}

/**
 * 抖动网格布点：把画布切成 cols×rows 个单元格，每个单元中心加小幅随机偏移。
 * 相比纯随机，能消除成团结块与大片留白，同时保留自然的不规则感。
 */
const initParticles = () => {
  if (!viewW || !viewH) return

  const count = resolveParticleCount()
  linkDist = resolveLinkDistance(count)
  const aspect = viewW / viewH
  const cols = Math.max(1, Math.round(Math.sqrt(count * aspect)))
  const rows = Math.max(1, Math.round(count / cols))
  const cellW = viewW / cols
  const cellH = viewH / rows
  const jitter = 0.42

  const next: Particle[] = []
  for (let row = 0; row < rows; row += 1) {
    for (let col = 0; col < cols; col += 1) {
      const jitterX = (Math.random() - 0.5) * jitter
      const jitterY = (Math.random() - 0.5) * jitter
      const x = Math.min(viewW, Math.max(0, (col + 0.5 + jitterX) * cellW))
      const y = Math.min(viewH, Math.max(0, (row + 0.5 + jitterY) * cellH))
      next.push({
        x,
        y,
        homeX: x,
        homeY: y,
        phase: Math.random() * Math.PI * 2,
        speed: 0.25 + Math.random() * 0.45,
        radius: 0.18 + Math.random() * 0.22,
        r: 1.3 + Math.random() * 1.1,
      })
    }
  }

  particles = next
}

const handleMouseMove = (event: MouseEvent) => {
  const canvas = canvasRef.value
  if (!canvas) return

  const rect = canvas.getBoundingClientRect()
  mouse.x = event.clientX - rect.left
  mouse.y = event.clientY - rect.top
}

const handleMouseLeave = () => {
  mouse.x = null
  mouse.y = null
}

const drawFrame = () => {
  const ctx = context
  if (!ctx || !viewW || !viewH) return

  ctx.clearRect(0, 0, viewW, viewH)

  const time = performance.now() / 1000

  particles.forEach((particle) => {
    // 围绕网格锚点做小幅椭圆摆动：持续有动感，又不会漂移抱团
    const angle = time * particle.speed + particle.phase
    const offset = particle.radius * Math.min(viewW, viewH)
    particle.x = Math.min(viewW, Math.max(0, particle.homeX + Math.cos(angle) * offset))
    particle.y = Math.min(viewH, Math.max(0, particle.homeY + Math.sin(angle * 1.15) * offset * 0.75))

    ctx.beginPath()
    ctx.arc(particle.x, particle.y, particle.r, 0, Math.PI * 2)
    ctx.fillStyle = props.particleColor
    ctx.fill()
  })

  for (let i = 0; i < particles.length; i += 1) {
    for (let j = i + 1; j < particles.length; j += 1) {
      const dx = particles[i].x - particles[j].x
      const dy = particles[i].y - particles[j].y
      const dist = Math.sqrt(dx * dx + dy * dy)

      if (dist < linkDist) {
        ctx.globalAlpha = 0.5 * (1 - dist / linkDist)
        ctx.strokeStyle = props.particleColor
        ctx.beginPath()
        ctx.moveTo(particles[i].x, particles[i].y)
        ctx.lineTo(particles[j].x, particles[j].y)
        ctx.stroke()
        ctx.globalAlpha = 1
      }
    }
  }

  if (mouse.x != null && mouse.y != null) {
    const mouseX = mouse.x
    const mouseY = mouse.y

    particles.forEach((particle) => {
      const dx = particle.x - mouseX
      const dy = particle.y - mouseY
      const dist = Math.sqrt(dx * dx + dy * dy)

      if (dist < linkDist) {
        ctx.globalAlpha = 1 - dist / linkDist
        ctx.strokeStyle = props.mouseLinkColor
        ctx.beginPath()
        ctx.moveTo(particle.x, particle.y)
        ctx.lineTo(mouseX, mouseY)
        ctx.stroke()
        ctx.globalAlpha = 1
      }
    })
  }
}

const animate = () => {
  drawFrame()
  animationFrame = window.requestAnimationFrame(animate)
}

/** 尺寸变化时同步画布并按新面积重排，保证缩放后依然均匀 */
const handleResize = () => {
  if (resizeFrame) return
  resizeFrame = window.requestAnimationFrame(() => {
    resizeFrame = 0
    if (!setupCanvasSize()) return
    initParticles()
    if (prefersReducedMotion) drawFrame()
  })
}

onMounted(() => {
  const canvas = canvasRef.value
  if (!canvas) return

  try {
    context = canvas.getContext('2d')
  } catch {
    context = null
  }
  if (!context) return

  setupCanvasSize()
  initParticles()

  prefersReducedMotion = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false

  if (typeof ResizeObserver !== 'undefined') {
    resizeObserver = new ResizeObserver(handleResize)
    resizeObserver.observe(canvas)
  } else {
    window.addEventListener('resize', handleResize)
  }
  window.addEventListener('mousemove', handleMouseMove)
  window.addEventListener('mouseleave', handleMouseLeave)

  if (prefersReducedMotion || typeof window.requestAnimationFrame !== 'function') {
    drawFrame()
    return
  }

  animate()
})

onUnmounted(() => {
  if (animationFrame && typeof window.cancelAnimationFrame === 'function') {
    window.cancelAnimationFrame(animationFrame)
  }
  if (resizeFrame && typeof window.cancelAnimationFrame === 'function') {
    window.cancelAnimationFrame(resizeFrame)
  }
  resizeObserver?.disconnect()
  resizeObserver = null
  window.removeEventListener('resize', handleResize)
  window.removeEventListener('mousemove', handleMouseMove)
  window.removeEventListener('mouseleave', handleMouseLeave)
  context = null
  particles = []
})
</script>

<template>
  <canvas ref="canvasRef" class="interactive-particle-canvas" />
</template>

<style scoped>
.interactive-particle-canvas {
  position: absolute;
  inset: 0;
  display: block;
  width: 100%;
  height: 100%;
  pointer-events: none;
}
</style>
