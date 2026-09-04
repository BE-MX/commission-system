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
})
document.documentElement.dataset.lexicalReady = 'true'
