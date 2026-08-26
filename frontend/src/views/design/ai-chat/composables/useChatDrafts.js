// Drafts stay in memory, scoped to this mounted workspace; never mix session attachments.
export function useChatDrafts({ prompt, attachments, modes, sessionId }) {
  const drafts = new Map()
  const key = () => sessionId.value ?? 'new'
  function save() {
    drafts.set(key(), { prompt: prompt.value, attachments: [...attachments.value], mode: modes.selected.value })
  }
  function restore({ locked = false } = {}) {
    const draft = drafts.get(key())
    if (!draft) return
    prompt.value = draft.prompt
    if (!sessionId.value) attachments.value = draft.attachments
    if (!locked) {
      modes.restore(draft.mode)
      if (draft.mode && !draft.mode.version) modes.select(draft.mode, { force: true })
    }
  }
  function materialize(id) {
    drafts.delete('new')
    drafts.delete(id)
  }
  return { save, restore, materialize }
}
