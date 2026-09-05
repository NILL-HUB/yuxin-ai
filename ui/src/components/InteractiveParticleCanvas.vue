<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue'

const props = withDefaults(
  defineProps<{
    particleCount?: number
    linkDistance?: number
    particleColor?: string
    mouseLinkColor?: string
  }>(),
  {
    particleCount: 80,
    linkDistance: 100,
    particleColor: '#3b82f6',
    mouseLinkColor: '#0ea5e9',
  },
)

type Particle = {
  x: number
  y: number
  vx: number
  vy: number
}

const canvasRef = ref<HTMLCanvasElement | null>(null)
let context: CanvasRenderingContext2D | null = null
let particles: Particle[] = []
let animationFrame = 0
let prefersReducedMotion = false
const mouse: { x: number | null; y: number | null } = { x: null, y: null }

const resizeCanvas = () => {
  const canvas = canvasRef.value
  if (!canvas || !context) return
  canvas.width = canvas.clientWidth
  canvas.height = canvas.clientHeight
}

const initParticles = () => {
  const canvas = canvasRef.value
  if (!canvas) return

  particles = Array.from({ length: props.particleCount }, () => ({
    x: Math.random() * canvas.width,
    y: Math.random() * canvas.height,
    vx: Math.random() * 0.6 - 0.3,
    vy: Math.random() * 0.6 - 0.3,
  }))
}

const handleMouseMove = (event: MouseEvent) => {
  const canvas = canvasRef.value
  if (!canvas) return

  const rect = canvas.getBoundingClientRect()
  mouse.x = event.clientX - rect.left
  mouse.y = event.clientY - rect.top
}

const drawFrame = () => {
  const canvas = canvasRef.value
  const ctx = context
  if (!canvas || !ctx) return

  ctx.clearRect(0, 0, canvas.width, canvas.height)

  particles.forEach((particle) => {
    particle.x += particle.vx
    particle.y += particle.vy

    if (particle.x <= 0 || particle.x >= canvas.width) particle.vx *= -1
    if (particle.y <= 0 || particle.y >= canvas.height) particle.vy *= -1

    ctx.beginPath()
    ctx.arc(particle.x, particle.y, 2, 0, Math.PI * 2)
    ctx.fillStyle = props.particleColor
    ctx.fill()
  })

  for (let i = 0; i < particles.length; i++) {
    for (let j = i + 1; j < particles.length; j++) {
      const dx = particles[i].x - particles[j].x
      const dy = particles[i].y - particles[j].y
      const dist = Math.sqrt(dx * dx + dy * dy)

      if (dist < props.linkDistance) {
        ctx.globalAlpha = 1 - dist / props.linkDistance
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

      if (dist < props.linkDistance) {
        ctx.globalAlpha = 1 - dist / props.linkDistance
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

onMounted(() => {
  const canvas = canvasRef.value
  if (!canvas) return
  if (!canvas.clientWidth || !canvas.clientHeight) return

  try {
    context = canvas.getContext('2d')
  } catch {
    context = null
  }
  if (!context) return

  resizeCanvas()
  initParticles()

  window.addEventListener('resize', resizeCanvas)
  window.addEventListener('mousemove', handleMouseMove)

  prefersReducedMotion = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false
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
  window.removeEventListener('resize', resizeCanvas)
  window.removeEventListener('mousemove', handleMouseMove)
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
