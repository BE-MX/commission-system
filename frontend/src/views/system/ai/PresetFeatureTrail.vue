<template>
  <div class="preset-trail">
    <span class="preset-trail__feature" :class="{ 'is-unassigned': !preset.feature_key }">
      {{ featureLabel }}
    </span>
    <span class="preset-trail__sep" aria-hidden="true">›</span>
    <span class="preset-trail__name">{{ preset.preset_name }}</span>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  preset: { type: Object, required: true },
})

const featureLabel = computed(() => props.preset.feature_label || (props.preset.feature_key ? props.preset.feature_key : '未归属'))
</script>

<style scoped>
.preset-trail { font-size: 13px; line-height: 1.4; min-width: 0; }
.preset-trail__feature { color: var(--text-muted); }
.preset-trail__feature.is-unassigned { color: var(--tag-danger-text); font-weight: 600; }
.preset-trail__sep { color: var(--border-hover); margin: 0 5px; }
.preset-trail__name { font-family: var(--font-mono); font-weight: 600; color: var(--text-primary); word-break: break-all; }
</style>
