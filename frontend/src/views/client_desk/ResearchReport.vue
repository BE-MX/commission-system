<template>
  <div v-if="report?.status === 'ready'" class="report">
    <div class="verdict panel">
      <div class="head">
        <span class="eyebrow">{{ report.report_markdown ? '背调报告' : '背调结论' }}</span>
        <span class="muted">{{ meta }}</span>
        <el-tag size="small" :type="underReview ? 'warning' : 'info'">{{ reviewLabel }}</el-tag>
      </div>
      <p v-if="report.verdict && !report.report_markdown">{{ report.verdict }}</p>
    </div>
    <div v-if="rendered" class="panel markdown" v-html="rendered"></div>
    <template v-else>
      <section v-for="section in report.sections" :key="section.key" class="panel">
        <h4>{{ section.label }}</h4>
        <ul><li v-for="(statement, index) in section.statements" :key="index">{{ statement }}</li></ul>
      </section>
    </template>
    <button v-if="report.event_key && showEvidence" type="button" class="link-button" @click="$emit('evidence', report.event_key)">查看背调来源 ↘</button>
  </div>
  <div v-else class="empty-state" role="status">
    <h3>无背调结果</h3>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import DOMPurify from 'dompurify'
import { Marked } from 'marked'
import { formatBeijingDate } from '@/utils/datetime'

const props = defineProps({
  report: { type: Object, default: null },
  showEvidence: { type: Boolean, default: false },
})
defineEmits(['evidence'])
const meta = computed(() => [
  props.report?.generated_at && formatBeijingDate(props.report.generated_at),
  props.report?.source_count ? `${props.report.source_count} 条来源` : '',
].filter(Boolean).join(' · '))
const underReview = computed(() => ['pending', 'revision_requested'].includes(props.report?.review_status))
const reviewLabel = computed(() => {
  if (props.report?.review_status === 'not_required') return '免审'
  return props.report?.reviewed ? '已审核' : '未审核'
})
const parser = new Marked({ gfm: true, breaks: true, renderer: { html: () => '', image: () => '' } })
const marker = '〔待核实〕'

const rendered = computed(() => {
  const body = props.report?.report_markdown
  if (!body) return ''
  const fragment = DOMPurify.sanitize(parser.parse(body), {
    RETURN_DOM_FRAGMENT: true,
    ALLOWED_TAGS: ['a', 'p', 'br', 'strong', 'em', 'del', 'blockquote', 'pre', 'code',
      'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'hr', 'ul', 'ol', 'li', 'table', 'thead', 'tbody', 'th', 'td', 'tr'],
    ALLOWED_ATTR: ['href', 'title', 'start'],
    ALLOW_DATA_ATTR: false,
    ALLOW_ARIA_ATTR: false,
  })
  for (const link of fragment.querySelectorAll('a')) {
    const href = link.getAttribute('href') || ''
    if (!/^https?:\/\//i.test(href) || link.textContent.includes(marker) || href.includes(encodeURIComponent(marker))) {
      link.replaceWith(...link.childNodes)
      continue
    }
    link.target = '_blank'
    link.rel = 'noopener noreferrer'
    link.referrerPolicy = 'no-referrer'
  }
  const walker = document.createTreeWalker(fragment, NodeFilter.SHOW_TEXT)
  const markedNodes = []
  while (walker.nextNode()) {
    if (walker.currentNode.data.includes(marker)) markedNodes.push(walker.currentNode)
  }
  for (const node of markedNodes) {
    const parts = node.data.split(marker)
    const replacement = document.createDocumentFragment()
    replacement.append(parts[0])
    for (const part of parts.slice(1)) {
      const badge = document.createElement('mark')
      badge.textContent = marker
      replacement.append(badge, part)
    }
    node.replaceWith(replacement)
  }
  const wrapper = document.createElement('div')
  wrapper.append(fragment)
  return wrapper.innerHTML
})
</script>

<style src="./board.css" scoped></style>
<style scoped>
.report { display: grid; gap: 12px; }
.verdict { border-color: var(--tag-gold-border); background: linear-gradient(145deg, var(--tag-gold-bg), var(--card-bg) 72%); }
.head { display: flex; align-items: center; flex-wrap: wrap; gap: 10px; }
.head .eyebrow { margin-right: auto; }
.eyebrow { color: var(--button-primary-text); font: 700 11px var(--font-display); letter-spacing: 0.1em; }
.verdict p { margin: 8px 0 0; font-size: 15px; line-height: 1.7; }
ul { margin: 0; padding-left: 18px; }
li { margin: 4px 0; line-height: 1.7; color: var(--text-secondary); overflow-wrap: anywhere; }
.panel + .panel { margin-top: 0; }
.markdown { overflow: auto; overflow-wrap: anywhere; line-height: 1.7; }
.markdown :deep(h1), .markdown :deep(h2), .markdown :deep(h3) { font-family: var(--font-display); }
.markdown :deep(table) { border-collapse: collapse; }
.markdown :deep(th), .markdown :deep(td) { min-width: 75px; border: 1px solid var(--border-color); padding: 4px 8px; }
.markdown :deep(pre) { overflow: auto; }
.markdown :deep(mark) {
  background: var(--tag-gold-bg); color: var(--tag-gold-text); border: 1px solid var(--tag-gold-border);
  border-radius: 4px; padding: 0 3px; font-weight: 700;
}
.report > .link-button { justify-self: start; }
</style>
