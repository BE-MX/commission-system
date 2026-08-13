<template>
  <el-dialog
    :model-value="modelValue"
    :title="detail?.title || '审批文档'"
    width="760px"
    @update:model-value="$emit('update:modelValue', $event)"
  >
    <div v-if="detail" class="review-detail">
      <div class="review-meta">冻结修订 v{{ detail.version_no }} · 提交人 ID {{ detail.submitted_by }}</div>
      <KnowledgeDocumentPreview :content="detail.content_json" />
      <section v-if="detail.ai_sources?.length" class="review-sources">
        <strong>AI 优化引用来源</strong>
        <ul>
          <li v-for="source in detail.ai_sources" :key="source.revision_id">
            {{ source.library_name }} / {{ source.title }}（修订 {{ source.revision_id }}）
          </li>
        </ul>
        <el-checkbox
          v-if="detail.requires_cross_library_confirmation"
          v-model="crossLibraryConfirmed"
        >我已核对跨知识库来源及其访问权限</el-checkbox>
      </section>
    </div>
    <template #footer>
      <GlassButton variant="ghost" @click="$emit('reject')">驳回</GlassButton>
      <GlassButton
        variant="primary"
        :disabled="detail?.requires_cross_library_confirmation && !crossLibraryConfirmed"
        @click="$emit('approve', crossLibraryConfirmed)"
      >批准并发布此版本</GlassButton>
    </template>
  </el-dialog>
</template>

<script setup>
import { ref, watch } from 'vue'
import KnowledgeDocumentPreview from './KnowledgeDocumentPreview.vue'

const props = defineProps({
  modelValue: Boolean,
  detail: { type: Object, default: null },
})
defineEmits(['update:modelValue', 'approve', 'reject'])
const crossLibraryConfirmed = ref(false)

watch(
  () => [props.modelValue, props.detail?.id],
  () => { crossLibraryConfirmed.value = false },
)
</script>

<style scoped>
.review-detail { display: grid; gap: 12px; }
.review-meta { color: var(--text-muted-blue); font-size: 13px; }
.review-sources { padding: 12px 14px; border: 1px solid var(--border-color); border-radius: var(--radius-md, 10px); color: var(--text-secondary); background: var(--surface-subtle); }
.review-sources ul { margin: 8px 0 10px; padding-left: 20px; }
</style>
