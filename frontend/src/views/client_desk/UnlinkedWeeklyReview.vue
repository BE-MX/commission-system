<template>
  <section class="weekly">
    <p v-if="leads.reviewLoading.value" class="muted center" role="status">正在读取周报…</p>
    <div v-else-if="leads.reviewError.value" class="empty-state">
      <h3>暂时无法读取</h3><p>{{ leads.reviewError.value }}</p><el-button @click="leads.loadReview">重试</el-button>
    </div>
    <div v-else-if="leads.review.value?.status === 'running'" class="empty-state">
      <h3>周报正在生成</h3>
      <el-button @click="leads.loadReview">刷新</el-button>
    </div>
    <div v-else-if="!leads.review.value || leads.review.value.status !== 'succeeded'" class="empty-state">
      <h3>尚未生成周报</h3>
      <p>生成后会列出遗漏任务、突破点、疑似老客和可清理线索。</p>
      <el-button v-permission="'client_desk:write'" type="primary" :loading="leads.generating.value" @click="leads.generateReview">生成</el-button>
    </div>
    <template v-else>
      <div class="panel overview">
        <div class="muted">周起始 {{ leads.review.value.week_start_date }}</div>
        <div v-if="overviewHtml" class="markdown" v-html="overviewHtml" />
        <p v-else class="muted">总览暂不可用，可以查看下方仍有效的行动条目。</p>
      </div>
      <div v-for="section in leads.sections.value" :key="section.key" class="panel section">
        <h4>{{ section.title }} <small>{{ section.rows.length }}</small></h4>
        <p v-if="!section.rows.length" class="muted">该周无此项。</p>
        <div v-for="row in section.rows" :key="row.id" class="row">
          <div class="copy">
            <span>{{ row.text }}</span>
            <span v-if="row.sub" class="muted">{{ row.sub }}</span>
          </div>
          <el-button
            v-if="row.action !== 'bind' || row.matchedCompanyId"
            v-permission="'client_desk:write'"

            :disabled="sameThread(leads.busyId.value, row.threadId)"
            @click="leads.actOnReviewRow(row)"
          >{{ row.actionLabel }}</el-button>
        </div>
      </div>
    </template>
  </section>
</template>

<script setup>
import { computed } from 'vue'
import DOMPurify from 'dompurify'
import { Marked } from 'marked'
import { sameThread } from './unlinkedLeadsModel'

const props = defineProps({ leads: { type: Object, required: true } })

// Overview text comes from the model; render it without raw HTML.
const parser = new Marked({ gfm: true, breaks: true, renderer: { html: () => '', image: () => '' } })
const overviewHtml = computed(() => {
  const body = props.leads.review.value?.overview_md
  if (!body) return ''
  return DOMPurify.sanitize(parser.parse(body), { ALLOWED_TAGS: ['p', 'br', 'strong', 'em', 'ul', 'ol', 'li', 'h1', 'h2', 'h3', 'h4', 'blockquote', 'code'], ALLOWED_ATTR: [] })
})
</script>

<style src="./board.css" scoped></style>
<style scoped>
.weekly { display: grid; gap: 12px; }
.center { padding: 30px; text-align: center; }
.overview { display: grid; gap: 6px; }
.markdown :deep(p) { margin: 4px 0; line-height: 1.7; }
.section h4 { display: flex; align-items: center; gap: 6px; }
.section h4 small { color: var(--text-secondary); font-size: 12px; font-weight: 500; }
.row { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 8px 0; border-top: 1px solid var(--border-color); }
.row:first-of-type { border-top: 0; }
.copy { display: grid; gap: 2px; min-width: 0; line-height: 1.6; }
</style>
