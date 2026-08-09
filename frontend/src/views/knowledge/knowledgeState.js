const ROLE_CAPABILITIES = Object.freeze({
  viewer: Object.freeze({ read: true, write: false, review: false, admin: false }),
  editor: Object.freeze({ read: true, write: true, review: false, admin: false }),
  reviewer: Object.freeze({ read: true, write: false, review: true, admin: false }),
  admin: Object.freeze({ read: true, write: true, review: true, admin: true }),
})

const EMPTY = Object.freeze({ read: false, write: false, review: false, admin: false })

export function capabilitiesFor(role) {
  return { ...(ROLE_CAPABILITIES[role] || EMPTY) }
}

export function documentActions({ role, pendingApprovalId }) {
  const capabilities = capabilitiesFor(role)
  return {
    canSave: capabilities.write,
    canSubmit: capabilities.write && !pendingApprovalId,
  }
}
