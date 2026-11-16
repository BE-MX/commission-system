import test from 'node:test'
import assert from 'node:assert/strict'
import { visibleMessages, answerVersions } from '../src/views/design/ai-chat/versions.js'

const messages = [
  { id: 1, role: 'user', selected_answer_id: 2 },
  { id: 2, role: 'assistant', reply_to_message_id: 1, content: 'original', status: 'completed' },
  { id: 3, role: 'assistant', reply_to_message_id: 1, content: 'regenerated', status: 'completed' },
]
test('reopening honors explicit selection and local preview never mutates it', () => {
  assert.equal(visibleMessages(messages)[1].id, 2)
  assert.equal(visibleMessages(messages, { 1: 3 })[1].id, 3)
  assert.equal(messages[0].selected_answer_id, 2)
  assert.equal(visibleMessages(messages)[1].id, 2)
})
test('streaming version is visible while preserving prior answer and question ordering', () => {
  const newer = [...messages, { id: 4, role: 'assistant', reply_to_message_id: 1, content: 'original', status: 'streaming' }]
  assert.deepEqual(visibleMessages(newer).map(item => item.id), [1, 4])
  assert.equal(answerVersions(newer, 1).length, 3)
  assert.equal(messages[1].content, 'original')
})
test('versions stay associated with their own question', () => {
  const newer = [...messages, { id: 4, role: 'user' }, { id: 5, role: 'assistant', reply_to_message_id: 4, content: 'next', status: 'completed' }]
  assert.deepEqual(visibleMessages(newer, { 1: 3, 4: 2 }).map(item => item.id), [1, 3, 4, 5])
})
test('legacy history defaults to latest usable answer instead of a failed retry', () => {
  const legacy = [{ id: 1, role: 'user' }, ...messages.slice(1), { id: 4, role: 'assistant', reply_to_message_id: 1, content: 'failed', status: 'failed' }]
  assert.equal(visibleMessages(legacy)[1].id, 3)
  assert.equal(visibleMessages(legacy, { 1: 4 })[1].id, 4)
})
