<template>
  <div class="flex min-h-full w-full items-center justify-center bg-slate-50 p-6">
    <div class="w-full max-w-xl rounded-xl border border-slate-200 bg-white p-10 text-center shadow-sm">
      <div class="mx-auto flex h-14 w-14 items-center justify-center rounded-full bg-blue-50 text-2xl">✦</div>
      <h1 class="mt-5 text-2xl font-semibold text-slate-900">
        {{ t('studio.placeholder.title') }}
      </h1>
      <p class="mt-3 text-sm leading-6 text-slate-500">
        {{ t('studio.placeholder.description') }}
      </p>
      <div class="mt-6 flex items-center justify-center gap-3">
        <button
          type="button"
          class="rounded-lg bg-blue-600 px-5 py-2 text-sm text-white transition-colors hover:bg-blue-700"
          @click="goStore"
        >
          {{ t('studio.placeholder.store') }}
        </button>
        <button
          type="button"
          class="rounded-lg border border-slate-200 px-5 py-2 text-sm text-slate-600 transition-colors hover:bg-slate-50"
          @click="goShowcase"
        >
          {{ t('studio.placeholder.showcase') }}
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

const goShowcase = () => {
  router.push('/showcase')
}
</script>
