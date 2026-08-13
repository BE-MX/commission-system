import test from 'node:test'
import assert from 'node:assert/strict'

import { capabilitiesFor, documentActions } from '../src/views/knowledge/knowledgeState.js'


test('library roles expose only their intended capabilities', () => {
  assert.deepEqual(capabilitiesFor('viewer'), { read: true, write: false, review: false, admin: false, deleteNode: false, deleteLibrary: false })
  assert.deepEqual(capabilitiesFor('editor'), { read: true, write: true, review: false, admin: false, deleteNode: true, deleteLibrary: false })
  assert.deepEqual(capabilitiesFor('reviewer'), { read: true, write: false, review: true, admin: false, deleteNode: false, deleteLibrary: false })
  assert.deepEqual(capabilitiesFor('admin'), { read: true, write: true, review: true, admin: true, deleteNode: true, deleteLibrary: true })
})


test('document actions reflect workflow state without hiding draft editing', () => {
  assert.deepEqual(documentActions({ role: 'editor', status: 'draft', pendingApprovalId: null }), { canSave: true, canSubmit: true, canDelete: true })
  assert.deepEqual(documentActions({ role: 'editor', status: 'pending', pendingApprovalId: 9 }), { canSave: true, canSubmit: false, canDelete: true })
  assert.deepEqual(documentActions({ role: 'editor', pendingApprovalId: null, canEdit: false }), { canSave: false, canSubmit: false, canDelete: false })
  assert.deepEqual(documentActions({ role: 'viewer', status: 'published', pendingApprovalId: null }), { canSave: false, canSubmit: false, canDelete: false })
})
