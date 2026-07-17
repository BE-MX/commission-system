<template>
  <!-- MD 渲染：marked 解析 + DOMPurify 消毒（原生 HTML 不消毒就是存储型 XSS，偷的是全员 token） -->
  <div class="md" v-html="html"></div>
</template>

<script setup>
import { computed } from 'vue'
import { marked } from 'marked'
import DOMPurify from 'dompurify'

marked.setOptions({ breaks: true, gfm: true })

const props = defineProps({ source: { type: String, default: '' } })

const html = computed(() =>
  DOMPurify.sanitize(marked.parse(props.source || ''), {
    FORBID_TAGS: ['style', 'form', 'input', 'button', 'iframe', 'object', 'embed'],
    FORBID_ATTR: ['style', 'onerror', 'onclick', 'onload'],
  })
)
</script>

<style>
/* 编辑感排版：MD 正文用衬线，表格/代码用等宽 */
.md { font-size: 14px; line-height: 1.85; color: var(--ink); word-break: break-word; }
.md h1, .md h2, .md h3, .md h4 { font-family: var(--font-serif); margin: 1.2em 0 0.5em; }
.md h1 { font-size: 1.5em; } .md h2 { font-size: 1.3em; } .md h3 { font-size: 1.12em; }
.md p { margin: 0.6em 0; }
.md ul, .md ol { padding-left: 1.5em; margin: 0.6em 0; }
.md li { margin: 0.25em 0; }
.md blockquote {
  margin: 0.8em 0; padding: 2px 0 2px 14px;
  border-left: 2px solid var(--cinnabar-line); color: var(--ink-2);
}
.md code {
  font-family: var(--font-mono); font-size: 0.88em;
  background: var(--paper-sunken); padding: 1px 5px; border-radius: 3px;
}
.md pre {
  background: var(--paper-sunken); border: 1px solid var(--hairline);
  border-radius: var(--radius); padding: 12px 14px; overflow-x: auto;
}
.md pre code { background: none; padding: 0; }
.md table { border-collapse: collapse; margin: 0.8em 0; width: 100%; font-size: 0.92em; }
.md th, .md td { border: 1px solid var(--hairline-strong); padding: 6px 10px; text-align: left; }
.md th { background: var(--paper-sunken); font-weight: 600; }
.md hr { border: none; border-top: 1px solid var(--hairline); margin: 1.4em 0; }
.md a { color: var(--cinnabar); text-decoration: underline; text-underline-offset: 3px; }
.md img { max-width: 100%; border-radius: var(--radius); }
</style>
