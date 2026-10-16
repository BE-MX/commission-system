<template>
  <section class="customer-tag-board" aria-label="当前客户标签">
    <div class="board-heading">
      <div>
        <strong>当前客户标签</strong>
        <p>{{ selectable ? '先选择本次文件使用的标签；已添加标签会在这个客户的下次预约中保留。' : '标签保存在客户名下，下次预约会自动显示。' }}</p>
      </div>
      <GlassButton variant="secondary" left-icon="Plus" :disabled="disabled" @click="$emit('add')">添加客户标签</GlassButton>
    </div>
    <div v-if="groups.length" class="dimension-list">
      <div v-for="group in groups" :key="group.id" class="dimension-row">
        <span class="dimension-label">{{ group.label }}</span>
        <div class="dimension-values">
          <span v-if="!group.tags.length" class="dimension-empty">尚未添加标签</span>
          <span v-for="tag in group.tags" :key="tag.tag_value_id" class="customer-tag-wrap"
            :class="{ 'has-lock-control': lockable && selectable, selected: selectable && selectedTagIds.includes(tag.tag_value_id), locked: lockedTagIds.includes(tag.tag_value_id) }">
          <button
            type="button"
            class="customer-tag"
            :class="{ selected: selectable && selectedTagIds.includes(tag.tag_value_id) }"
            :disabled="!selectable || disabled || lockedTagIds.includes(tag.tag_value_id)"
            :title="lockedTagIds.includes(tag.tag_value_id) ? '已锁定选择，取消锁定后可修改' : undefined"
            :aria-pressed="selectable ? selectedTagIds.includes(tag.tag_value_id) : undefined"
            @click="$emit('toggle', tag)"
          >{{ tag.value }}</button>
          <button v-if="lockable && selectable" type="button" class="customer-tag-lock"
            :disabled="disabled || !selectedTagIds.includes(tag.tag_value_id)"
            :aria-pressed="lockedTagIds.includes(tag.tag_value_id)"
            :aria-label="`${lockedTagIds.includes(tag.tag_value_id) ? '取消锁定' : '锁定选择'} ${tag.value}`"
            :title="lockedTagIds.includes(tag.tag_value_id) ? '取消锁定选择' : '锁定选择：文件夹识别时保留此标签'"
            @click.stop="$emit('toggle-lock', tag)">
            <el-icon aria-hidden="true"><Lock v-if="lockedTagIds.includes(tag.tag_value_id)" /><Unlock v-else /></el-icon>
          </button>
          <button v-if="deletable" type="button" class="customer-tag-delete" :disabled="disabled"
            :aria-label="`删除标签 ${tag.value}`" @click.stop="$emit('delete', tag)">×</button>
          </span>
        </div>
      </div>
    </div>
    <el-empty v-else description="这位客户还没有标签，可从标签库添加" :image-size="54" />
  </section>
</template>

<script setup>
import { computed } from 'vue'
import { Lock, Unlock } from '@element-plus/icons-vue'
import GlassButton from '@/components/GlassButton.vue'

const props = defineProps({
  dimensions: { type: Array, default: () => [] },
  tags: { type: Array, default: () => [] },
  selectedTagIds: { type: Array, default: () => [] },
  lockedTagIds: { type: Array, default: () => [] },
  selectable: { type: Boolean, default: false },
  disabled: { type: Boolean, default: false },
  deletable: { type: Boolean, default: false },
  lockable: { type: Boolean, default: false },
})
defineEmits(['add', 'toggle', 'toggle-lock', 'delete'])

const groups = computed(() => {
  const byId = new Map()
  for (const dim of props.dimensions) byId.set(dim.id, { id: dim.id, label: dim.label, tags: [] })
  for (const tag of props.tags) {
    if (!byId.has(tag.dimension_id)) byId.set(tag.dimension_id, { id: tag.dimension_id, label: tag.dimension_label || '客户标签', tags: [] })
    byId.get(tag.dimension_id).tags.push(tag)
  }
  return [...byId.values()]
})
</script>

<style scoped>
.customer-tag-board { padding: 16px; border: 1px solid var(--border-color); border-radius: 12px; background: var(--card-bg); }
.board-heading { display: flex; justify-content: space-between; align-items: flex-start; gap: 16px; margin-bottom: 14px; }
.board-heading strong { font-size: 15px; }
.board-heading p { margin: 5px 0 0; color: var(--text-secondary); font-size: 12px; }
.dimension-list { display: grid; gap: 10px; }
.dimension-row { display: grid; grid-template-columns: 110px minmax(0, 1fr); align-items: start; gap: 12px; }
.dimension-label { padding-top: 6px; color: var(--text-secondary); font-size: 12px; font-weight: 600; }
.dimension-values { display: flex; flex-wrap: wrap; gap: 8px; }
.dimension-empty { padding: 6px 0; color: var(--text-muted); font-size: 12px; }
.customer-tag { padding: 6px 11px; border: 1px solid var(--border-color); border-radius: 999px; color: var(--text-secondary); background: var(--card-bg); font-size: 12px; }
.customer-tag:enabled { cursor: pointer; }
.customer-tag:enabled:hover { border-color: var(--color-primary); color: var(--color-primary-text); }
.customer-tag.selected { border-color: var(--color-primary); color: var(--color-primary-text); background: var(--color-primary-light); font-weight: 600; }
.customer-tag-wrap { position: relative; display: inline-flex; }
.customer-tag-wrap .customer-tag { padding-right: 22px; }
.has-lock-control { padding-right: 28px; }
.has-lock-control .customer-tag { padding-right: 6px; border-radius: 999px 0 0 999px; }
.customer-tag-lock { display: grid; place-items: center; min-width: 28px; min-height: 28px; padding: 0 7px; border: 1px solid var(--border-color); border-left: 0; border-radius: 0 999px 999px 0; background: var(--card-bg); color: var(--text-secondary); cursor: pointer; }
.selected .customer-tag-lock { border-color: var(--color-primary); background: var(--color-primary-light); color: var(--color-primary-text); }
.locked .customer-tag-lock { background: var(--button-primary); color: var(--button-primary-ink); }
.customer-tag-lock:disabled { cursor: not-allowed; opacity: 0.5; }
.customer-tag-lock:focus-visible { outline: 2px solid var(--color-primary); outline-offset: 2px; }
.customer-tag-delete { position: absolute; top: -8px; right: -8px; display: grid; place-items: center; width: 24px; height: 24px; padding: 0; border: 1px solid var(--border-color); border-radius: 50%; background: var(--card-bg); color: var(--color-danger); cursor: pointer; font-size: 17px; line-height: 1; }
.customer-tag-delete:hover { border-color: var(--color-danger); }
.has-lock-control .customer-tag-delete { top: 50%; right: 0; transform: translateY(-50%); }
@media (max-width: 700px) { .board-heading { flex-direction: column; }.dimension-row { grid-template-columns: 1fr; gap: 5px; } }
</style>
