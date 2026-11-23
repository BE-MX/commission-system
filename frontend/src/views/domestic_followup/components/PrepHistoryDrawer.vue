<template>
  <el-drawer v-model="visible" title="历史准备卡" :direction="isMobile ? 'btt' : 'rtl'" :size="isMobile ? '88%' : '620px'" append-to-body destroy-on-close>
    <div v-loading="loading" class="history-body">
      <el-alert type="info" :closable="false" title="当前负责人可只读查看全部准备卡；只有作者能修改。当时的资料范围按作者权限生成。" />
      <div class="history-layout">
        <nav class="history-list" aria-label="准备卡列表">
          <button v-for="row in rows" :key="row.id" type="button" :aria-current="selected?.id === row.id" @click="selected = row">
            <strong>{{ row.template_code }} · {{ row.goal }}</strong>
            <span>{{ row.author_name }}<el-tag v-if="row.readonly" size="small" effect="plain">前任 / 同事</el-tag></span>
            <small>{{ row.created_at?.slice(0, 10) }} · {{ statusLabels[row.status] || row.status }}</small>
          </button>
        </nav>
        <section v-if="selected" class="history-detail">
          <div class="readonly-banner">只读 · {{ selected.author_name }} 写于 {{ selected.created_at?.slice(0, 10) }}</div>
          <h3>{{ selected.template_code }} · {{ selected.goal }}</h3>
          <dl><dt>联系依据</dt><dd>{{ selected.contact_reason || '未填写' }}</dd><dt>用于跟进</dt><dd>{{ selected.followup_id ? `#${selected.followup_id}` : '尚未使用' }}</dd></dl>
          <h4>已知</h4>
          <ul><li v-for="(fact, index) in selected.known_facts" :key="index">{{ fact.text }}<small>{{ fact.source_kind }} · {{ fact.observed_at || '日期未知' }}</small></li></ul>
          <template v-if="selected.strategy">
            <h4>策略</h4><h3>{{ selected.strategy.headline }}</h3><p>{{ selected.strategy.why }}</p>
            <h4>开场白</h4><p>{{ selected.strategy.opening || '不适用' }}</p>
            <h4>关键问题</h4><ol><li v-for="(question, index) in selected.strategy.key_questions" :key="index">{{ question.q }}</li></ol>
          </template>
          <el-empty v-else description="这张卡还没有生成策略" :image-size="64" />
        </section>
      </div>
    </div>
    <template #footer>
      <div class="history-actions">
        <GlassButton @click="visible = false">关闭</GlassButton>
        <GlassButton v-if="selected?.can_clone" :variant="canRecord ? 'secondary' : 'primary'" :loading="cloning" @click="clone">基于此卡新建</GlassButton>
        <GlassButton v-if="canRecord" v-permission="'domestic_followup:write'" variant="primary" :disabled="cloning" @click="record">沟通完了，记结果</GlassButton>
      </div>
    </template>
  </el-drawer>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import GlassButton from '@/components/GlassButton.vue'
import { apiError, followupApi } from '@/api/domesticFollowup'
import { msgError } from '@/utils/feedback'
import { newRequestId } from '../followupDraft'

const emit = defineEmits(['cloned', 'record'])
const visible = ref(false), loading = ref(false), cloning = ref(false), rows = ref([]), selected = ref(null)
const canRecord = computed(() => selected.value?.readonly === false && !selected.value.followup_id
  && ['draft', 'ready'].includes(selected.value.status))
let loadRequest = 0
const statusLabels = { draft: '草稿', ready: '待使用', used: '已使用', abandoned: '已作废', expired: '已过期' }
const media = window.matchMedia('(max-width: 768px)'), isMobile = ref(media.matches)
const sync = event => { isMobile.value = event.matches }
onMounted(() => media.addEventListener('change', sync))
onBeforeUnmount(() => media.removeEventListener('change', sync))
async function open(row) {
  const request = ++loadRequest
  rows.value = []
  selected.value = null
  visible.value = true
  loading.value = true
  try {
    const cards = await followupApi.preps(row.id)
    if (request !== loadRequest) return
    rows.value = cards
    selected.value = cards[0] || null
  } catch (e) {
    if (request === loadRequest) msgError(apiError(e, '历史准备卡加载失败'), e)
  } finally {
    if (request === loadRequest) loading.value = false
  }
}
function record() {
  if (!canRecord.value || cloning.value) return
  visible.value = false
  emit('record', selected.value)
}
async function clone() {
  cloning.value = true
  try {
    const prep = await followupApi.clonePrep(selected.value.id, { request_id: newRequestId() })
    visible.value = false
    emit('cloned', prep)
  } catch (e) { msgError(apiError(e, '新建准备卡失败'), e) }
  finally { cloning.value = false }
}
defineExpose({ open })
</script>

<style scoped>
.history-body { display: flex; flex-direction: column; gap: 14px; }
.history-actions { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 8px; }
.history-layout { display: grid; grid-template-columns: 210px minmax(0, 1fr); gap: 14px; }
.history-list { display: flex; flex-direction: column; gap: 8px; }
.history-list button { display: flex; flex-direction: column; gap: 5px; padding: 10px; border: 1px solid var(--border-color); border-radius: var(--radius-sm); background: transparent; text-align: left; cursor: pointer; }
.history-list button[aria-current="true"] { border-color: var(--color-primary); background: var(--tag-gold-bg); }
.history-list span { display: flex; align-items: center; gap: 6px; color: var(--text-secondary); font-size: 12px; }
.history-list small { color: var(--text-secondary); }
.history-detail { min-width: 0; }
.history-detail h3 { margin: 12px 0 8px; }
.history-detail h4 { margin: 16px 0 6px; }
.history-detail p, .history-detail li { line-height: 1.65; }
.history-detail li small { display: block; color: var(--text-secondary); }
.readonly-banner { padding: 9px 12px; border-radius: var(--radius-sm); color: var(--text-secondary); background: var(--tag-neutral-bg); font-size: 12px; }
dl { display: grid; grid-template-columns: 72px 1fr; gap: 6px 10px; }
dt { color: var(--text-secondary); } dd { margin: 0; }
@media (max-width: 600px) { .history-layout { grid-template-columns: 1fr; } .history-list { flex-direction: row; overflow-x: auto; } .history-list button { min-width: 190px; } }
</style>
