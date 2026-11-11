<template>
  <div v-if="item" class="radar-detail">
    <div class="detail-heading">
      <span class="project-icon" :class="`project-icon--${item.kind}`">{{ item.kind === 'repo' ? 'Git' : item.kind === 'article' ? '文' : 'Web' }}</span>
      <div class="detail-heading__main">
        <a :href="item.canonical_url" target="_blank" rel="noopener noreferrer" class="detail-link">{{ item.host }}{{ item.kind === 'repo' ? item.canonical_url.split(item.host)[1] : '' }} ↗</a>
        <div class="detail-heading__meta">
          <span>{{ item.language || item.item_type }}</span>
          <span>收录于 {{ formatDate(item.created_at) }}</span>
          <StatusBadge v-if="item.scan_mode === 'agent'" type="primary">agent 扫描</StatusBadge>
          <StatusBadge v-else type="info">程序扫描</StatusBadge>
        </div>
      </div>
    </div>

    <section v-if="!readOnly" class="detail-controls">
      <el-radio-group :model-value="item.status" @update:model-value="value => emit('patch', { status: value })">
        <el-radio-button v-for="(label, value) in STATUS" :key="value" :value="value">{{ label }}</el-radio-button>
      </el-radio-group>
      <el-select :model-value="item.watch_level" aria-label="关注级别" @update:model-value="value => emit('patch', { watch_level: value })">
        <el-option v-for="(label, value) in WATCH" :key="value" :label="`关注：${label}`" :value="value" />
      </el-select>
      <p>{{ WATCH_HELP[item.watch_level] }}</p>
    </section>

    <el-alert v-if="item.last_error" type="warning" :closable="false" show-icon :title="item.last_error" />

    <section v-for="(label, field) in aiSuggestions" v-show="item.ai_suggestions?.[field] !== undefined" :key="field" class="suggestion">
      <span>AI 对「{{ label }}」有新建议</span>
      <GlassButton @click="emit('patch', { accept_suggestion: field })">采纳建议</GlassButton>
    </section>

    <section class="detail-section">
      <h3>标题与类型 <span class="ai-label">{{ locked('title') ? '已锁定' : 'AI 生成' }}</span></h3>
      <template v-if="readOnly"><h2 class="detail-title">{{ item.title }}</h2><p class="muted">{{ typeLabel(item.item_type) }}</p></template>
      <div v-else class="inline-fields">
        <el-input :model-value="draft.title" aria-label="项目标题" @update:model-value="value => draft.title = value" />
        <el-select v-model="draft.item_type" aria-label="项目类型">
          <el-option v-for="type in types" :key="type.code" :label="type.label" :value="type.code" />
        </el-select>
        <GlassButton @click="saveTitleAndType">保存</GlassButton>
      </div>
    </section>

    <section class="detail-section">
      <div class="section-title"><h3>一句话说明 <span class="ai-label">{{ locked('one_liner') ? '已锁定' : 'AI 生成' }}</span></h3><GlassButton v-if="!readOnly && !editingOne" variant="link" @click="editingOne = true">编辑</GlassButton></div>
      <p v-if="readOnly || !editingOne" class="one-liner">{{ item.one_liner || '待补充' }}</p>
      <template v-else>
        <el-input v-model="draft.one_liner" type="textarea" :rows="2" maxlength="500" show-word-limit />
        <div class="edit-actions"><GlassButton @click="editingOne = false">取消</GlassButton><GlassButton variant="primary" @click="saveOneLiner">保存并锁定</GlassButton></div>
      </template>
    </section>

    <section class="detail-section">
      <div class="section-title"><h3>可用于方舟 <span class="ai-label">{{ locked('ark_modules') ? '已锁定' : 'AI 生成' }}</span></h3><GlassButton v-if="!readOnly" variant="link" :disabled="draft.ark_modules.length >= 3" @click="draft.ark_modules.push({ name: '', reason: '', effort: '中' })">添加</GlassButton></div>
      <el-empty v-if="!item.ark_modules.length && readOnly" description="暂无推荐" :image-size="56" />
      <div class="module-list">
        <div v-for="(module, index) in readOnly ? item.ark_modules : draft.ark_modules" :key="index" class="module-card">
          <template v-if="readOnly">
            <StatusBadge type="warning">{{ module.name }}</StatusBadge><p>{{ module.reason }}</p><small>落地难度 {{ module.effort }}</small>
          </template>
          <template v-else>
            <div class="module-card__top"><el-select v-model="module.name" placeholder="选择模块" filterable><el-option v-for="entry in modules" :key="entry.code" :label="entry.label" :value="entry.label" /></el-select><el-select v-model="module.effort" class="effort"><el-option v-for="level in ['低', '中', '高']" :key="level" :label="`难度 ${level}`" :value="level" /></el-select></div>
            <el-input v-model="module.reason" type="textarea" :rows="2" placeholder="适用理由" />
            <GlassButton variant="link" link-tone="danger" @click="draft.ark_modules.splice(index, 1)">移除</GlassButton>
          </template>
        </div>
      </div>
      <div v-if="!readOnly" class="edit-actions"><GlassButton :disabled="!draft.ark_modules.every(item => item.name)" @click="emit('patch', { overrides: { ark_modules: draft.ark_modules } })">保存模块推荐</GlassButton></div>
    </section>

    <section class="detail-section">
      <h3>版本与更新</h3>
      <div class="fact-grid">
        <div><span>版本</span><b>{{ item.version || '无版本' }}</b></div>
        <div><span>最近更新</span><b>{{ formatDate(item.last_updated_at) }}</b></div>
        <div><span>Star</span><b>{{ item.stars ?? '—' }}</b></div>
        <div><span>协议</span><b>{{ item.license || '—' }}</b></div>
      </div>
      <p class="fact-source">版本与日期来自数据源，不由 AI 生成。精确时间：{{ formatDateTime(item.last_updated_at) }}</p>
      <div v-if="item.unread_update" class="update-box">
        <b>{{ item.unread_update.from_version ? `${item.unread_update.from_version} → ` : '' }}{{ item.unread_update.to_version || '最近更新' }}</b>
        <ul><li v-for="(line, index) in item.unread_update.summary" :key="index">{{ line }}</li></ul>
        <p v-if="item.unread_update.ark_impact">对方舟：{{ item.unread_update.ark_impact }}</p>
        <small>{{ item.unread_update.ai_reason }}</small>
      </div>
      <el-timeline v-if="item.updates?.length" class="update-timeline">
        <el-timeline-item v-for="update in item.updates" :key="update.id" :timestamp="update.detected_at" placement="top">
          <div class="timeline-title"><StatusBadge :type="update.level === 'key' ? 'warning' : update.level === 'normal' ? 'primary' : 'info'">{{ levelLabel(update.level) }}</StatusBadge><b>{{ update.to_version || '更新记录' }}</b></div>
          <p v-for="(line, index) in update.summary" :key="index">{{ line }}</p>
          <small v-if="update.ai_reason">{{ update.ai_reason }}</small>
        </el-timeline-item>
      </el-timeline>
    </section>

    <section class="detail-section">
      <div class="section-title"><h3>详细说明 <span class="ai-label">{{ locked('description') ? '已锁定' : 'AI 生成' }}</span></h3></div>
      <p v-if="readOnly" class="description">{{ item.description || '暂无详细说明' }}</p>
      <template v-else><el-input v-model="draft.description" type="textarea" :rows="5" placeholder="能做什么、怎么用、限制与部署要求" /><div class="edit-actions"><GlassButton @click="emit('patch', { overrides: { description: draft.description } })">保存详细说明</GlassButton></div></template>
    </section>

    <section class="detail-section">
      <h3>来源</h3>
      <div v-for="source in item.sources" :key="source.id" class="source-row">
        <StatusBadge type="info">{{ CHANNEL[source.channel] || source.channel }}</StatusBadge>
        <div><a :href="source.source_url" target="_blank" rel="noopener noreferrer">{{ source.source_url }}</a><p>{{ source.created_at }}<span v-if="source.raw_text"> · {{ source.raw_text }}</span></p></div>
      </div>
    </section>

    <section class="detail-section">
      <h3>标签与我的笔记</h3>
      <template v-if="readOnly"><div class="tag-list"><StatusBadge v-for="tag in item.tags" :key="tag" type="warning">#{{ tag }}</StatusBadge></div><p class="description">{{ item.note || '暂无笔记' }}</p></template>
      <template v-else>
        <el-select v-model="draft.tags" multiple filterable allow-create default-first-option placeholder="输入标签后回车" class="tag-editor"><el-option v-for="tag in item.tags" :key="tag" :label="tag" :value="tag" /></el-select>
        <el-input v-model="draft.note" type="textarea" :rows="3" placeholder="试用结论、注意事项…" />
        <div class="edit-actions"><GlassButton @click="emit('patch', { tags: draft.tags, note: draft.note })">保存标签与笔记</GlassButton></div>
      </template>
    </section>
  </div>
</template>

<script setup>
import { reactive, ref, watch } from 'vue'
import GlassButton from '@/components/GlassButton.vue'
import StatusBadge from '@/components/StatusBadge.vue'
import { formatBeijingDate, formatBeijingDateTime } from '@/utils/datetime'

const props = defineProps({
  item: { type: Object, default: null },
  readOnly: { type: Boolean, default: false },
  types: { type: Array, default: () => [] },
  modules: { type: Array, default: () => [] },
})
const emit = defineEmits(['patch'])
const STATUS = { inbox: '待看', trying: '试用中', adopted: '已采用', dropped: '已放弃' }
const WATCH = { key: '重点', normal: '普通', adopted: '已采用', silent: '静默' }
const WATCH_HELP = { key: '关键与普通更新都推送，普通更新 7 天最多一次', normal: '只推送关键更新', adopted: '只推送破坏性与安全更新', silent: '只记录，不推送' }
const CHANNEL = { dingtalk: '钉钉', web: '方舟页面', mcp: 'MCP', github_star: 'GitHub Star', insight: 'AI 工具速递' }
const editingOne = ref(false)
const draft = reactive({ title: '', item_type: 'other', one_liner: '', description: '', ark_modules: [], tags: [], note: '' })
const aiSuggestions = { one_liner: '一句话说明', description: '详细说明', title: '标题', item_type: '类型', ark_modules: '模块推荐' }

watch(() => props.item, item => {
  if (!item) return
  Object.assign(draft, {
    title: item.title, item_type: item.item_type, one_liner: item.one_liner,
    description: item.description, ark_modules: JSON.parse(JSON.stringify(item.ark_modules || [])),
    tags: [...(item.tags || [])], note: item.note,
  })
}, { immediate: true, deep: true })

const locked = field => props.item.locked_fields?.includes(field)
const typeLabel = code => props.types.find(item => item.code === code)?.label || ({ open_source: '开源项目', saas: 'SaaS 工具', ai_model: 'AI 模型', mcp_skill: 'MCP / Skill', dev_tool: '开发工具', article: '文章教程', other: '其他' }[code] || code)
const formatDate = value => value ? formatBeijingDate(value) : '未知'
const formatDateTime = value => value ? formatBeijingDateTime(value, { seconds: false }) : '未知'
const levelLabel = level => ({ key: '关键', normal: '普通', noise: '噪音' }[level] || '记录')
function saveOneLiner() {
  emit('patch', { overrides: { one_liner: draft.one_liner.trim() } })
  editingOne.value = false
}
function saveTitleAndType() {
  emit('patch', { overrides: { title: draft.title.trim(), item_type: draft.item_type } })
}
</script>

<style scoped>
.radar-detail { display: grid; grid-template-columns: minmax(0, 1fr); gap: 4px; width: 100%; min-width: 0; }
.detail-heading { display: flex; gap: 12px; padding-bottom: 14px; }
.detail-heading__main { min-width: 0; }
.detail-heading__meta { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; margin-top: 8px; color: var(--text-muted); font-size: 12px; }
.project-icon { width: 40px; height: 40px; display: grid; place-items: center; flex-shrink: 0; border-radius: 11px; background: var(--sidebar-glass-to); color: var(--color-gold); font-weight: 700; }
.project-icon--website { background: var(--tag-info-bg); color: var(--tag-info-text); }
.project-icon--article { background: var(--tag-success-bg); color: var(--tag-success-text); }
.detail-link { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--text-secondary); font-family: var(--font-mono); font-size: 12px; }
.detail-controls { display: grid; grid-template-columns: 1fr auto; gap: 8px; align-items: center; }
.detail-controls p { grid-column: 1 / -1; margin: 0 0 8px; color: var(--text-muted); font-size: 12px; }
.detail-section { min-width: 0; padding: 16px 0; border-bottom: 1px solid var(--border-color); }
.detail-section:last-child { border-bottom: 0; }
.detail-section h3 { margin: 0 0 10px; color: var(--text-secondary); font-size: 13px; }
.section-title { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.ai-label { margin-left: 6px; padding: 2px 5px; border-radius: 4px; background: var(--tag-info-bg); color: var(--tag-info-text); font-size: 11px; }
.detail-title { margin: 0; font-size: 20px; overflow-wrap: anywhere; }
.muted, .fact-source, .source-row p, .update-timeline small { color: var(--text-muted); font-size: 12px; }
.inline-fields { display: grid; grid-template-columns: minmax(0, 1fr) 150px auto; gap: 8px; }
.one-liner { margin: 0; font-size: 15px; line-height: 1.7; overflow-wrap: anywhere; }
.edit-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 8px; }
.module-list { display: grid; gap: 8px; }
.module-card { padding: 10px; border: 1px solid var(--border-color); border-radius: 10px; background: var(--toolbar-bg); }
.module-card p { margin: 8px 0; color: var(--text-secondary); }
.module-card small { color: var(--text-muted); }
.module-card__top { display: grid; grid-template-columns: 1fr 110px; gap: 8px; margin-bottom: 8px; }
.fact-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; }
.fact-grid > div { padding: 10px; border: 1px solid var(--border-color); border-radius: 9px; }
.fact-grid span { display: block; color: var(--text-muted); font-size: 12px; }
.fact-grid b { display: block; margin-top: 4px; overflow-wrap: anywhere; font-family: var(--font-mono); font-size: 13px; }
.update-box { margin-top: 12px; padding: 12px; border: 1px solid var(--tag-gold-border); border-radius: 10px; background: var(--tag-gold-bg); }
.update-box ul { margin: 8px 0; padding-left: 18px; }
.update-box small { color: var(--text-muted); }
.update-timeline { margin-top: 18px; padding-left: 2px; }
.update-timeline p { margin: 4px 0; color: var(--text-secondary); }
.timeline-title { display: flex; align-items: center; gap: 8px; }
.description { white-space: pre-wrap; color: var(--text-secondary); line-height: 1.7; }
.source-row { display: flex; gap: 10px; padding: 8px 0; }
.source-row + .source-row { border-top: 1px dashed var(--border-color); }
.source-row > div { min-width: 0; }
.source-row a { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--text-secondary); }
.source-row p { margin: 3px 0 0; overflow-wrap: anywhere; }
.tag-list { display: flex; flex-wrap: wrap; gap: 6px; }
.tag-editor { width: 100%; margin-bottom: 10px; }
.suggestion { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-top: 8px; padding: 8px 10px; border-radius: 8px; background: var(--tag-info-bg); color: var(--tag-info-text); font-size: 12px; }
@media (max-width: 640px) {
  .detail-controls { grid-template-columns: 1fr; }
  .fact-grid { grid-template-columns: repeat(2, 1fr); }
  .inline-fields { grid-template-columns: 1fr; }
}
</style>
