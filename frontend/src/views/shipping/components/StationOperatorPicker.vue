<template>
  <section class="operator-picker" :class="{ 'needs-selection': attention && !selectedId }" aria-labelledby="operator-title">
    <div class="picker-heading"><h2 id="operator-title">第一步 · 选择本次操作人</h2><span>{{ people.length }} 人</span></div>
    <p>请点击自己的姓名，再开始扫描</p>
    <input v-if="people.length > 12" v-model="search" class="operator-search" type="search" placeholder="搜索姓名" aria-label="搜索质检人员" />
    <div v-if="loading" role="status">正在加载质检人员…</div>
    <div v-else-if="!people.length" role="status">暂无可选人员，请重试或联系管理员</div>
    <div v-else class="operator-grid" role="radiogroup" aria-labelledby="operator-title">
      <label v-for="person in filtered" :key="person.id" class="operator-card" :class="{ selected: person.id === selectedId }">
        <input type="radio" name="shipping-operator" :value="person.id" :checked="person.id === selectedId" :disabled="disabled" @change="$emit('choose', person)" />
        <span v-if="person.id === selectedId" :key="attention" class="operator-glow" aria-hidden="true" />
        <span class="operator-name">{{ person.name }}<small v-if="person.hint">{{ person.hint }}</small></span>
        <span v-if="person.id === selectedId" class="operator-check" aria-hidden="true">✓</span>
      </label>
    </div>
    <p v-if="search && !filtered.length">没有匹配的人员</p>
  </section>
</template>
<script setup>
import { computed, ref } from 'vue'
const props = defineProps({ people: { type: Array, default: () => [] }, selectedId: Number, disabled: Boolean, loading: Boolean, attention: Number })
defineEmits(['choose'])
const search = ref('')
const filtered = computed(() => props.people.filter(p => `${p.name} ${p.hint}`.includes(search.value.trim())))
</script>
<style scoped>
.operator-picker{padding:16px 0}.picker-heading{display:flex;align-items:center;justify-content:space-between;gap:8px}.picker-heading h2{font-size:16px;margin:0}.picker-heading>span,.operator-picker>p{font-size:13px;color:var(--text-secondary)}
.operator-picker>p{margin:8px 0 10px}
.operator-search{box-sizing:border-box;width:100%;border:1px solid var(--border-color);border-radius:12px;padding:10px 12px;background:var(--card-bg);font-size:16px;margin-bottom:10px;color:var(--text-primary)}
.operator-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px}.operator-card{position:relative;isolation:isolate;box-sizing:border-box;display:flex;min-height:52px;align-items:center;justify-content:center;padding:8px 6px;border:2px solid var(--border-color);border-radius:12px;background:var(--card-bg);cursor:pointer;transition:transform 120ms,border-color 180ms,background-color 180ms}
.operator-card:active{transform:scale(.97)}.operator-card:has(input:disabled){cursor:default;opacity:.7}.operator-card:has(input:focus-visible){outline:3px solid var(--color-primary);outline-offset:3px}.operator-card input{position:absolute;width:1px;height:1px;opacity:0}.operator-card.selected{border-color:var(--color-primary);background:var(--color-gold-soft)}
.operator-name{font-size:16px;text-align:center;min-width:0;font-weight:750;overflow-wrap:anywhere;line-height:1.4}.operator-name small{display:block;font-size:11px;font-weight:400;color:var(--text-secondary)}.operator-check{position:absolute;right:3px;top:1px;font-size:11px;line-height:1;pointer-events:none}.selected .operator-check{color:var(--color-primary-hover);font-weight:700}
.operator-glow{position:absolute;inset:-4px;z-index:-1;border-radius:14px;box-shadow:0 0 0 5px var(--color-primary-glow);pointer-events:none;animation:operator-pulse 280ms cubic-bezier(.23,1,.32,1) both}.needs-selection{border-top:2px solid var(--color-primary)}
@keyframes operator-pulse{from{opacity:1;transform:scale(.98)}to{opacity:0;transform:scale(1.08)}}
@media(prefers-reduced-motion:reduce){.operator-card{transition:none}.operator-card:active{transform:none}.operator-glow{animation:none;display:none}}
</style>
