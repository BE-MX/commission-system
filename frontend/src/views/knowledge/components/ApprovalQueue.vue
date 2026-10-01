<template>
  <DetailDrawer :model-value="modelValue" title="待审批文档" width="640px" @update:model-value="$emit('update:modelValue', $event)">
    <ListPageStatus :paged="false" :error="readError" :loading="readLoading" :has-data="items.length > 0" @retry="$emit('retry')" />
    <el-empty v-if="readLoaded && !readLoading && !readError && !items.length" description="当前没有待审批文档" />
    <div v-if="items.length" class="approval-list">
      <article v-for="(item, index) in items" :key="item.id" class="approval-card" :style="{ '--stagger': Math.min(index, 6) }">
        <div>
          <h3>{{ item.title }}</h3>
          <p>提交人 ID {{ item.submitted_by }} · 修订 #{{ item.revision_id }}</p>
        </div>
        <div class="approval-actions">
          <GlassButton variant="primary" @click="$emit('inspect', item)">审阅冻结版本</GlassButton>
        </div>
      </article>
    </div>
  </DetailDrawer>
</template>

<script setup>
defineProps({ modelValue: Boolean, readError: String, readLoading: Boolean, readLoaded: Boolean, items: { type: Array, default: () => [] } })
defineEmits(['update:modelValue', 'inspect', 'retry'])
</script>

<style scoped>
.approval-list { display: grid; gap: 12px; }
.approval-card { padding: 16px; border: 1px solid var(--border-color); border-radius: var(--radius-lg, 12px); animation: card-in .22s var(--ease-out-strong, ease-out) both; animation-delay: calc(var(--stagger, 0) * 45ms); transition: border-color .18s ease, box-shadow .18s ease, transform .18s var(--ease-out-strong, ease-out); }
.approval-card h3 { margin: 0 0 6px; color: var(--text-primary); font-size: 16px; }
.approval-card p { margin: 0; color: var(--text-muted-blue); font-size: 12px; }
.approval-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 16px; }
@keyframes card-in { from { opacity: 0; transform: translateY(10px); } to { opacity: 1; transform: translateY(0); } }
@media (hover: hover) and (pointer: fine) { .approval-card:hover { border-color: var(--color-primary); box-shadow: var(--card-shadow-hover); transform: translateY(-2px); } }
@media (prefers-reduced-motion: reduce) { .approval-card { animation: none; transition: none; } }
</style>
