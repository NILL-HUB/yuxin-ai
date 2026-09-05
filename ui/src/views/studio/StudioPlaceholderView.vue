<template>
  <div
    class="flex min-h-full w-full items-center justify-center p-6"
    style="
      background:
        radial-gradient(1200px 600px at 15% 10%, rgba(233, 30, 99, 0.08), transparent 60%),
        radial-gradient(1000px 500px at 85% 90%, rgba(214, 51, 132, 0.1), transparent 55%),
        var(--aicss-bg);
    "
  >
    <div
      class="w-full max-w-xl rounded-[var(--aicss-radius-lg)] border border-[var(--aicss-border)] bg-[var(--aicss-surface)] p-10 text-center shadow-[var(--aicss-shadow-card)]"
    >
      <div
        class="mx-auto flex h-14 w-14 items-center justify-center rounded-full bg-[var(--aicss-accent-soft)] text-2xl"
        style="color: var(--aicss-accent)"
      >
        <icon-edit class="text-xl" />
      </div>
      <h1 class="mt-5 text-2xl font-semibold" style="color: var(--aicss-text)">
        {{ t('studio.placeholder.title') }}
      </h1>
      <p class="mt-3 text-sm leading-6" style="color: var(--aicss-muted)">
        {{ t('studio.placeholder.description') }}
      </p>
      <div class="mt-6 flex flex-wrap items-center justify-center gap-3">
        <button
          type="button"
          class="rounded-[var(--aicss-radius)] bg-[var(--aicss-accent)] px-5 py-2 text-sm font-medium text-white transition-colors hover:bg-[var(--aicss-accent-text)] focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-[var(--aicss-accent)]"
          @click="goStore"
        >
          {{ t('studio.placeholder.store') }}
        </button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'

const { t } = useI18n()
const router = useRouter()

const goStore = () => {
  router.push('/store/public-apps')
}

</script>
