export function answerVersions(messages, questionId) {
  return messages.filter(item => item.role === 'assistant' && item.reply_to_message_id === questionId)
}

export function visibleMessages(messages, previews = {}) {
  return messages.flatMap(question => {
    if (question.role !== 'user') return []
    const versions = answerVersions(messages, question.id)
    const latest = versions.at(-1)
    const selected = versions.find(item => item.id === question.selected_answer_id)
    const preview = versions.find(item => item.id === previews[question.id])
    const usable = versions.filter(item => ['completed', 'stopped'].includes(item.status) && item.content).at(-1)
    const answer = latest?.status === 'streaming' ? latest : preview || selected || usable || latest
    return answer ? [question, answer] : [question]
  })
}
