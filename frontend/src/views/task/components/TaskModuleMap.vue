<template>
  <div class="module-map">
    <section v-for="g in groups" :key="g.group_key" class="mm-group lg-card is-static">
      <h3>{{ g.group_title }}<span>{{ g.open }} 项未结束</span></h3>
      <div v-for="m in g.items" :key="m.key" class="mm-row">
        <button type="button" class="mm-cell" @click="emit('pick', m.key)">
          <span class="mm-name">{{ m.title }}</span>
          <span v-if="m.hasP0" class="mm-p0" title="含 P0 任务" />
          <span class="mm-heat"><i :style="{ width: `${(m.open / max) * 100}%` }" /></span>
          <span class="mm-num">{{ m.open }}</span>
        </button>
        <button
          v-if="m.isPrivate"
          v-permission="'task:write'"
          type="button"
          class="mm-remove"
          :aria-label="`停用分类「${m.title}」`"
          @click="emit('remove-custom', m)"
        >×</button>
      </div>
      <el-button v-if="g.group_key === 'custom'" v-permission="'task:write'" link type="primary" class="mm-add" @click="emit('add-custom')">+ 新分类</el-button>
    </section>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({ groups: { type: Array, required: true } })
const emit = defineEmits(['pick', 'add-custom', 'remove-custom'])
const max = computed(() => Math.max(1, ...props.groups.flatMap(g => g.items.map(m => m.open))))
</script>

<style scoped>
.module-map { display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 14px; }
.mm-group { padding: 16px; }
.mm-group h3 { display: flex; justify-content: space-between; margin: 0 0 10px; font: 700 14px var(--font-display); }
.mm-group h3 span { font-size: 12px; font-weight: 600; color: var(--text-muted); }
.mm-cell {
  display: flex; align-items: center; gap: 10px; width: 100%; padding: 8px 10px; border: 0; border-radius: 10px;
  background: transparent; text-align: left; cursor: pointer; transition: background-color 150ms ease;
}
.mm-cell:hover { background: color-mix(in srgb, var(--card-bg) 80%, transparent); }
.mm-name { flex: 1; font-size: 13px; color: var(--text-primary); }
.mm-p0 { width: 8px; height: 8px; border-radius: 50%; background: var(--color-danger); }
.mm-heat { width: 70px; height: 8px; overflow: hidden; border-radius: 4px; background: var(--color-info-bg); }
.mm-heat i { display: block; height: 100%; background: linear-gradient(90deg, var(--color-gold), var(--color-primary)); }
.mm-num { width: 22px; font: 700 13px var(--font-display); text-align: right; font-variant-numeric: tabular-nums; }
.mm-row { display: flex; align-items: center; gap: 4px; }
.mm-remove { width: 24px; height: 24px; border: 0; border-radius: 6px; background: transparent; color: var(--text-muted); cursor: pointer; }
.mm-remove:hover { background: var(--color-danger-bg); color: var(--color-danger-text); }
.mm-add { margin-top: 6px; }
</style>
