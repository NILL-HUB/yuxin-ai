<template>
  <div class="flex min-h-full w-full items-center justify-center bg-slate-50 p-6">
    <div class="w-full max-w-md rounded-xl border border-slate-200 bg-white p-8 text-center shadow-sm">
      <div class="text-6xl font-bold text-slate-200">403</div>
      <h1 class="mt-3 text-xl font-semibold text-slate-900">无权访问</h1>
      <p class="mt-2 text-sm text-slate-500">
        当前管理员没有访问该页面的权限，请返回管理后台或联系超级管理员调整角色权限。
      </p>
      <div class="mt-6 flex items-center justify-center gap-3">
        <button
          type="button"
          class="rounded-lg border border-slate-200 px-4 py-2 text-sm text-slate-600 transition-colors hover:bg-slate-50"
          @click="goBack"
        >
          返回上一页
        </button>
        <button
          type="button"
          class="rounded-lg bg-blue-600 px-4 py-2 text-sm text-white transition-colors hover:bg-blue-700"
          @click="goDashboard"
        >
          返回管理后台
        </button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { useRouter } from 'vue-router'

const router = useRouter()

const goBack = () => {
  if (window.history.length > 1) {
    router.back()
    return
  }
  router.push('/admin')
}

const goDashboard = () => {
  router.push('/admin')
}
</script>
