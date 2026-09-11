import { $getRoot, createEditor } from 'lexical'
import { registerPlainText } from '@lexical/plain-text'

const editorRoot = document.getElementById('editor')!
const editor = createEditor({
  namespace: 'composer-browser-regression',
  onError(error) { throw error },
})
editor.setRootElement(editorRoot)
registerPlainText(editor)
editor.registerUpdateListener(({ editorState }) => {
  editorState.read(() => {
    document.documentElement.dataset.lexicalText = $getRoot().getTextContent()
  })
})
document.getElementById('send')!.addEventListener('click', () => {
  document.documentElement.dataset.sendClicked = 'true'
  if (document.documentElement.dataset.autoHarness === 'true') {
    const text = document.documentElement.dataset.lexicalText ?? ''
    const count = Number(document.documentElement.dataset.autoSent ?? 0) + 1
    document.documentElement.dataset.autoSent = String(count)
    const row = document.createElement('div'); row.style.alignItems = 'flex-end'; row.dataset.id = `true_synthetic_sent_${count}`
    const bubble = document.createElement('div'); bubble.dataset.testid = 'msg-container'
    const meta = document.createElement('div'); meta.className = 'copyable-text'; meta.dataset.prePlainText = '[10:00, 2026-09-11] Synthetic:'
    const span = document.createElement('span'); span.dataset.testid = 'selectable-text'; span.textContent = text
    meta.append(span); bubble.append(meta); row.append(bubble); document.querySelector('footer')!.before(row)
    editor.update(() => $getRoot().clear())
  }
})
document.documentElement.dataset.lexicalReady = 'true'
