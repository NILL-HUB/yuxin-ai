<script setup lang="ts">
interface ParticleSpec {
  left: number
  top: number
  size: number
  minOpacity: number
  maxOpacity: number
  duration: number
  delay: number
  scale: number
}

const particles: ParticleSpec[] = [
  { left: 8, top: 14, size: 12, minOpacity: 0.14, maxOpacity: 0.34, duration: 4.8, delay: 0, scale: 1.08 },
  { left: 14, top: 42, size: 10, minOpacity: 0.12, maxOpacity: 0.3, duration: 5.4, delay: 0.8, scale: 1.04 },
  { left: 18, top: 68, size: 14, minOpacity: 0.14, maxOpacity: 0.28, duration: 6.1, delay: 1.1, scale: 1.12 },
  { left: 28, top: 22, size: 11, minOpacity: 0.13, maxOpacity: 0.32, duration: 5.2, delay: 1.9, scale: 1.06 },
  { left: 32, top: 54, size: 16, minOpacity: 0.12, maxOpacity: 0.24, duration: 6.4, delay: 0.4, scale: 1.14 },
  { left: 42, top: 76, size: 13, minOpacity: 0.14, maxOpacity: 0.28, duration: 5.6, delay: 2.2, scale: 1.1 },
  { left: 50, top: 16, size: 12, minOpacity: 0.14, maxOpacity: 0.32, duration: 4.9, delay: 1.5, scale: 1.08 },
  { left: 56, top: 40, size: 18, minOpacity: 0.12, maxOpacity: 0.24, duration: 6.8, delay: 0.9, scale: 1.16 },
  { left: 60, top: 66, size: 11, minOpacity: 0.12, maxOpacity: 0.28, duration: 5.8, delay: 2.8, scale: 1.06 },
  { left: 70, top: 24, size: 14, minOpacity: 0.14, maxOpacity: 0.3, duration: 5.1, delay: 0.6, scale: 1.1 },
  { left: 74, top: 50, size: 20, minOpacity: 0.1, maxOpacity: 0.22, duration: 7.2, delay: 1.7, scale: 1.18 },
  { left: 80, top: 74, size: 12, minOpacity: 0.12, maxOpacity: 0.24, duration: 5.7, delay: 2.4, scale: 1.05 },
  { left: 88, top: 18, size: 9, minOpacity: 0.16, maxOpacity: 0.34, duration: 4.6, delay: 1.3, scale: 1.04 },
  { left: 90, top: 56, size: 13, minOpacity: 0.12, maxOpacity: 0.26, duration: 6.2, delay: 3.1, scale: 1.08 },
]
</script>

<template>
  <div class="admin-login-background" aria-hidden="true">
    <div class="background-base"></div>
    <div class="background-scan"></div>
    <div class="background-aurora aurora-primary"></div>
    <div class="background-aurora aurora-secondary"></div>
    <div class="background-aurora aurora-tertiary"></div>
    <div class="background-aurora aurora-quaternary"></div>
    <div class="background-aurora aurora-quinary"></div>
    <div class="background-aurora aurora-senary"></div>
    <div class="background-beam beam-left"></div>
    <div class="background-beam beam-right"></div>
    <div class="background-halo halo-main"></div>
    <div class="background-halo halo-side"></div>

    <span
      v-for="(particle, index) in particles"
      :key="index"
      class="background-particle"
      :style="{
        left: `${particle.left}%`,
        top: `${particle.top}%`,
        width: `${particle.size}px`,
        height: `${particle.size}px`,
        opacity: String(particle.minOpacity),
        transform: 'scale(0.88)',
        animationDuration: `${particle.duration}s`,
        animationDelay: `${particle.delay}s`,
        '--particle-min-opacity': String(particle.minOpacity),
        '--particle-max-opacity': String(particle.maxOpacity),
        '--particle-scale': String(particle.scale),
      }"
    />
  </div>
</template>

<style scoped>
.admin-login-background {
  position: absolute;
  inset: 0;
  overflow: hidden;
  pointer-events: none;
}

.background-base {
  position: absolute;
  inset: 0;
  background:
    radial-gradient(circle at 14% 20%, rgba(99, 132, 255, 0.18), transparent 24%),
    radial-gradient(circle at 84% 20%, rgba(68, 211, 255, 0.12), transparent 20%),
    radial-gradient(circle at 58% 78%, rgba(155, 108, 255, 0.12), transparent 22%),
    linear-gradient(145deg, #050814 0%, #0d1325 52%, #15132a 100%);
}

.background-scan {
  position: absolute;
  inset: 0;
  background:
    linear-gradient(90deg, rgba(5, 8, 20, 0) 10%, rgba(10, 16, 32, 0.08) 22%, rgba(14, 24, 42, 0.26) 42%, rgba(8, 12, 24, 0.54) 64%, rgba(7, 11, 20, 0.82) 100%);
  opacity: 0.76;
}

.background-aurora {
  position: absolute;
  border-radius: 999px;
  filter: blur(104px);
  mix-blend-mode: screen;
  opacity: 0.92;
}

.aurora-primary {
  top: -14%;
  left: -18%;
  width: 56%;
  height: 42%;
  background: rgba(97, 131, 255, 0.38);
  animation: aurora-float-primary 24s ease-in-out infinite alternate;
}

.aurora-secondary {
  top: 8%;
  right: -16%;
  width: 48%;
  height: 34%;
  background: rgba(77, 204, 255, 0.28);
  animation: aurora-float-secondary 26s ease-in-out infinite alternate;
}

.aurora-tertiary {
  bottom: -16%;
  left: 18%;
  width: 50%;
  height: 38%;
  background: rgba(162, 106, 255, 0.24);
  animation: aurora-float-tertiary 22s ease-in-out infinite alternate;
}

.aurora-quaternary {
  top: 34%;
  left: 42%;
  width: 40%;
  height: 30%;
  background: rgba(88, 162, 255, 0.22);
  animation: aurora-float-quaternary 18s ease-in-out infinite alternate;
}

.aurora-quinary {
  top: 16%;
  left: 22%;
  width: 34%;
  height: 28%;
  background: rgba(84, 245, 227, 0.14);
  animation: aurora-float-quinary 28s ease-in-out infinite alternate;
}

.aurora-senary {
  bottom: 6%;
  right: 6%;
  width: 42%;
  height: 30%;
  background: rgba(205, 126, 255, 0.18);
  animation: aurora-float-senary 20s ease-in-out infinite alternate;
}

.background-beam {
  position: absolute;
  width: 140%;
  height: 1px;
  margin-left: -20%;
  background: linear-gradient(
    90deg,
    transparent 0%,
    rgba(136, 170, 255, 0.12) 22%,
    rgba(125, 210, 255, 0.3) 50%,
    rgba(136, 170, 255, 0.12) 78%,
    transparent 100%
  );
  filter: blur(0.6px);
  opacity: 0.56;
}

.beam-left {
  top: 26%;
  transform: rotate(-10deg);
  animation: beam-float-left 18s ease-in-out infinite;
}

.beam-right {
  top: 68%;
  transform: rotate(14deg);
  animation: beam-float-right 21s ease-in-out infinite;
}

.background-halo {
  position: absolute;
  border-radius: 999px;
  border: 1px solid rgba(145, 180, 255, 0.12);
  opacity: 0.45;
}

.halo-main {
  top: 14%;
  right: 10%;
  width: 340px;
  height: 340px;
  animation: halo-pulse-main 10s ease-in-out infinite;
}

.halo-side {
  bottom: 8%;
  right: 18%;
  width: 220px;
  height: 220px;
  animation: halo-pulse-side 12s ease-in-out infinite;
}

.background-particle {
  position: absolute;
  display: block;
  border-radius: 999px;
  background: radial-gradient(circle, rgba(163, 196, 255, 0.9), rgba(163, 196, 255, 0));
  box-shadow: 0 0 24px rgba(145, 188, 255, 0.28);
  animation: particle-breathe ease-in-out infinite;
  animation-fill-mode: both;
  will-change: opacity, transform;
}

@keyframes aurora-float-primary {
  0% {
    transform: translate3d(0, 0, 0) scale(0.98);
  }

  35% {
    transform: translate3d(10%, 12%, 0) scale(1.08);
  }

  70% {
    transform: translate3d(24%, 2%, 0) scale(1.18);
  }

  100% {
    transform: translate3d(30%, 14%, 0) scale(1.14);
  }
}

@keyframes aurora-float-secondary {
  0% {
    transform: translate3d(0, 0, 0) scale(0.94);
  }

  30% {
    transform: translate3d(-14%, 10%, 0) scale(1.08);
  }

  65% {
    transform: translate3d(-30%, -2%, 0) scale(1.16);
  }

  100% {
    transform: translate3d(-36%, 18%, 0) scale(1.12);
  }
}

@keyframes aurora-float-tertiary {
  0% {
    transform: translate3d(0, 0, 0) scale(0.96);
  }

  40% {
    transform: translate3d(12%, -12%, 0) scale(1.08);
  }

  75% {
    transform: translate3d(-10%, -22%, 0) scale(1.14);
  }

  100% {
    transform: translate3d(8%, -28%, 0) scale(1.1);
  }
}

@keyframes aurora-float-quaternary {
  0% {
    transform: translate3d(0, 0, 0) scale(0.94);
  }

  50% {
    transform: translate3d(-16%, 8%, 0) scale(1.12);
  }

  100% {
    transform: translate3d(-24%, -10%, 0) scale(1.06);
  }
}

@keyframes aurora-float-quinary {
  0% {
    transform: translate3d(0, 0, 0) scale(0.96);
  }

  45% {
    transform: translate3d(26%, 14%, 0) scale(1.12);
  }

  100% {
    transform: translate3d(38%, -8%, 0) scale(1.08);
  }
}

@keyframes aurora-float-senary {
  0% {
    transform: translate3d(0, 0, 0) scale(0.92);
  }

  50% {
    transform: translate3d(-18%, -12%, 0) scale(1.08);
  }

  100% {
    transform: translate3d(-26%, -24%, 0) scale(1.14);
  }
}

@keyframes beam-float-left {
  0%,
  100% {
    transform: translate3d(0, 0, 0) rotate(-10deg);
  }

  50% {
    transform: translate3d(0, 12px, 0) rotate(-8deg);
  }
}

@keyframes beam-float-right {
  0%,
  100% {
    transform: translate3d(0, 0, 0) rotate(14deg);
  }

  50% {
    transform: translate3d(0, -10px, 0) rotate(12deg);
  }
}

@keyframes halo-pulse-main {
  0%,
  100% {
    transform: scale(0.92);
    opacity: 0.26;
  }

  50% {
    transform: scale(1.04);
    opacity: 0.48;
  }
}

@keyframes halo-pulse-side {
  0%,
  100% {
    transform: scale(0.96);
    opacity: 0.18;
  }

  50% {
    transform: scale(1.08);
    opacity: 0.34;
  }
}

@keyframes particle-breathe {
  0% {
    opacity: var(--particle-min-opacity);
    transform: scale(0.88);
  }

  50% {
    opacity: var(--particle-max-opacity);
    transform: scale(var(--particle-scale));
  }

  100% {
    opacity: var(--particle-min-opacity);
    transform: scale(0.9);
  }
}

@media (prefers-reduced-motion: reduce) {
  .background-aurora,
  .background-beam,
  .background-halo,
  .background-particle {
    animation: none !important;
  }
}
</style>
