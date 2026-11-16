import DOMPurify from 'dompurify'
import { Marked } from 'marked'

const markdown = new Marked({ gfm: true, breaks: true })

export function renderChatMarkdown(raw) {
  const clean = DOMPurify.sanitize(markdown.parse(raw || ''), { FORBID_TAGS: ['button', 'input', 'form', 'style'] })
  const container = document.createElement('div')
  container.innerHTML = clean
  for (const pre of container.querySelectorAll('pre')) {
    const code = pre.querySelector('code')
    if (!code) continue
    const toolbar = document.createElement('div')
    toolbar.className = 'code-toolbar'
    const language = document.createElement('span')
    language.textContent = [...code.classList].find(name => name.startsWith('language-'))?.slice(9) || '代码'
    const copy = document.createElement('button')
    copy.type = 'button'
    copy.className = 'copy-code'
    copy.textContent = '复制代码'
    toolbar.append(language, copy)
    pre.prepend(toolbar)
  }
  for (const link of container.querySelectorAll('a')) {
    link.target = '_blank'
    link.rel = 'noopener noreferrer'
  }
  return container.innerHTML
}
