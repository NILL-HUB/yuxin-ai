<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { type BalanceProfile } from '@/models/commerce'

defineProps<{
  profile: BalanceProfile | null
}>()

const { t } = useI18n()
</script>

<template>
  <section class="panel">
    <div class="panel-head">
      <span class="icon-badge"><icon-bulb /></span>
      <div class="head-copy">
        <h3>{{ t('membership.compute.title') }}</h3>
        <p>{{ t('membership.compute.description') }}</p>
      </div>
      <span v-if="profile?.high_rate_locked" class="lock-pill">
        <icon-check-circle /> {{ t('membership.compute.highRateLocked') }}
      </span>
    </div>

    <div class="compute-grid">
      <div class="compute-item accent">
        <span>{{ t('membership.compute.quotaCredit') }}</span>
        <strong>{{ profile?.quota_credit ?? 0 }}</strong>
      </div>
      <div class="compute-item">
        <span>{{ t('membership.compute.permanentCredit') }}</span>
        <strong>{{ profile?.permanent_credit ?? 0 }}</strong>
      </div>
    </div>

    <p v-if="profile?.high_rate_locked" class="info-line">
      <icon-info-circle class="info-ico" />
      消费时先扣套餐额度再扣永久算力，高佣金率已锁定。
    </p>
  </section>
</template>

<style scoped>
.panel {
  height: 100%;
  padding: 24px;
  border-radius: var(--aicss-radius-lg);
  border: 1px solid var(--aicss-border);
  background: var(--aicss-surface);
  box-shadow: var(--aicss-shadow-card);
  transition: box-shadow 0.2s ease;
}
.panel:hover {
  box-shadow: var(--aicss-shadow-elevated);
}

.panel-head {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-start;
  gap: 14px;
}

.icon-badge {
  display: flex;
  flex-shrink: 0;
  align-items: center;
  justify-content: center;
  width: 44px;
  height: 44px;
  border-radius: var(--aicss-radius);
  background: var(--aicss-accent);
  color: #fff;
  box-shadow: var(--aicss-shadow-card);
}
.icon-badge :deep(svg) {
  width: 20px;
  height: 20px;
}

.head-copy {
  min-width: 0;
  flex: 1;
}

.head-copy h3,
.head-copy p {
  margin: 0;
}

.head-copy h3 {
  font-family: var(--aicss-font-serif, Georgia, 'Songti SC', serif);
  font-size: 19px;
  letter-spacing: -0.02em;
  color: var(--aicss-text);
}

.head-copy p {
  margin-top: 4px;
  font-size: 12px;
  line-height: 1.55;
  color: var(--aicss-muted);
}

.lock-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  margin-left: auto;
  border-radius: 999px;
  background: var(--aicss-accent-soft);
  color: var(--aicss-accent-text);
  font-size: 12px;
  font-weight: 500;
  padding: 5px 12px;
  white-space: nowrap;
}
.lock-pill :deep(svg) {
  width: 14px;
  height: 14px;
}

.compute-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px;
  margin-top: 20px;
}

.compute-item {
  padding: 16px;
  border-radius: var(--aicss-radius);
  border: 1px solid var(--aicss-border);
  background: var(--aicss-bg-subtle);
  transition: box-shadow 0.18s ease;
}
.compute-item:hover {
  box-shadow: var(--aicss-shadow-card);
}

.compute-item.accent {
  border-color: color-mix(in srgb, var(--aicss-accent) 22%, var(--aicss-border));
  background: var(--aicss-accent-soft);
}

.compute-item span {
  color: var(--aicss-muted);
  font-size: 13px;
}

.compute-item strong {
  display: block;
  margin-top: 10px;
  font-family: 'SFMono-Regular', Consolas, Menlo, monospace;
  font-size: 26px;
  font-weight: 650;
  letter-spacing: -0.02em;
  color: var(--aicss-text);
  font-variant-numeric: tabular-nums;
}

.compute-item.accent strong {
  color: var(--aicss-accent-text);
}

.info-line {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  margin: 16px 0 0;
  font-size: 12px;
  line-height: 1.6;
  color: var(--aicss-muted);
}
.info-ico {
  flex-shrink: 0;
  margin-top: 2px;
  color: var(--aicss-accent-text);
}
.info-ico :deep(svg) {
  width: 14px;
  height: 14px;
}

@media (max-width: 720px) {
  .compute-grid {
    grid-template-columns: 1fr;
  }
}
</style>