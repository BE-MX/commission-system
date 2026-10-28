<template>
  <aside class="rail">
    <el-input
      :model-value="keyword" placeholder="搜索客户" clearable :prefix-icon="Search"
      @update:model-value="$emit('update:keyword', $event)"
    />
    <div class="rail-h"><span>我负责的客户</span><span>{{ customers.length }}</span></div>
    <div v-if="error" class="rail-err">
      {{ error }} <el-button link type="primary" @click="$emit('retry')">重试</el-button>
    </div>
    <div v-loading="loading" class="rail-list" role="listbox" aria-label="客户">
      <button
        v-for="c in customers" :key="c.customer_id" type="button" role="option"
        class="cust" :class="{ on: c.customer_id === selected }" :aria-selected="c.customer_id === selected"
        @click="$emit('update:selected', c.customer_id)"
      >
        <span class="flag" :style="{ background: tint(c.customer_id) }">{{ c.country_code || '—' }}</span>
        <span class="nm">
          <b>{{ c.display_name }}</b>
          <small>{{ c.assignment_role === 'collaborator' ? '协作' : c.assignment_role === 'primary' ? '主负责' : '管理可见' }}</small>
        </span>
        <span class="cnt">{{ c.swatch_count }}</span>
      </button>
      <p v-if="!loading && !customers.length && !error" class="rail-empty">暂无可用客户</p>
    </div>
  </aside>
</template>

<script setup>
import { Search } from '@element-plus/icons-vue'

defineProps({
  customers: { type: Array, default: () => [] },
  keyword: { type: String, default: '' },
  selected: { type: Number, default: null },
  loading: Boolean,
  error: { type: String, default: '' },
})
defineEmits(['update:keyword', 'update:selected', 'retry'])

const TINTS = ['var(--button-primary-text)', 'var(--button-success)', 'var(--color-info-text)', 'var(--button-warning)', 'var(--button-danger-text)']
const tint = (id) => TINTS[Number(id) % TINTS.length]
</script>

<style scoped>
.rail {
  position: sticky; top: 16px; padding: 14px; background: var(--card-bg); border-radius: var(--card-radius);
  border: 1px solid var(--border-color); box-shadow: var(--card-shadow);
}
.rail-h {
  display: flex; justify-content: space-between; margin: 14px 2px 8px;
  font: 700 10.5px var(--font-display); letter-spacing: 0.12em; color: var(--text-muted); text-transform: uppercase;
}
.rail-list { display: grid; gap: 2px; min-height: 60px; max-height: calc(100dvh - 240px); overflow: auto; }
.rail-err, .rail-empty { font-size: 12px; color: var(--text-muted); padding: 8px 4px; }
.cust {
  display: flex; align-items: center; gap: 10px; width: 100%; padding: 8px 10px; border: 0; border-radius: 10px;
  background: transparent; cursor: pointer; text-align: left;
  transition: background-color 160ms ease, transform 120ms ease-out;
}
.cust:active { transform: scale(0.98); }
.cust.on { background: var(--color-gold-soft); }
.cust:focus-visible { outline: 2px solid var(--button-focus); }
@media (hover: hover) and (pointer: fine) { .cust:not(.on):hover { background: var(--button-quiet-hover); } }
.flag {
  flex: 0 0 28px; height: 28px; border-radius: var(--radius-md, 8px); display: grid; place-items: center;
  font: 700 11px var(--font-display); color: var(--card-bg);
}
.nm { flex: 1; min-width: 0; display: grid; }
.nm b { font: 600 13px var(--font-display); color: var(--text-primary); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.nm small { font-size: 11.5px; color: var(--text-muted); }
.cnt { font: 600 12px var(--font-display); color: var(--text-secondary); background: var(--page-bg); border-radius: 6px; padding: 1px 7px; }

@media (max-width: 860px) {
  .rail { position: static; }
  .rail-list { display: flex; overflow-x: auto; max-height: none; gap: 8px; padding-bottom: 4px; }
  .cust { flex: 0 0 auto; width: auto; border: 1px solid var(--border-color); }
  .nm b { max-width: 140px; }
}
</style>
