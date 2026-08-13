const ROLE_CAPABILITIES = Object.freeze({
  viewer: Object.freeze({ read: true, write: false, review: false, admin: false, deleteNode: false, deleteLibrary: false }),
  editor: Object.freeze({ read: true, write: true, review: false, admin: false, deleteNode: true, deleteLibrary: false }),
  reviewer: Object.freeze({ read: true, write: false, review: true, admin: false, deleteNode: false, deleteLibrary: false }),
  admin: Object.freeze({ read: true, write: true, review: true, admin: true, deleteNode: true, deleteLibrary: true }),
})

const EMPTY = Object.freeze({ read: false, write: false, review: false, admin: false, deleteNode: false, deleteLibrary: false })

export function capabilitiesFor(role) {
  return { ...(ROLE_CAPABILITIES[role] || EMPTY) }
}

export function documentActions({ role, pendingApprovalId, canEdit = true }) {
  const capabilities = capabilitiesFor(role)
  const canWrite = capabilities.write && canEdit
  return {
    canSave: canWrite,
    canSubmit: canWrite && !pendingApprovalId,
    canDelete: capabilities.deleteNode && canEdit,
  }
}
