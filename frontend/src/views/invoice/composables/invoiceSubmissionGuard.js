export function createInvoiceSubmissionGuard(pendingKeys = new Set()) {
  const keyOf = id => String(id)

  return {
    isPending(id) {
      return pendingKeys.has(keyOf(id))
    },

    async run(id, submit) {
      const key = keyOf(id)
      if (pendingKeys.has(key)) return { duplicate: true }

      pendingKeys.add(key)
      try {
        return { duplicate: false, value: await submit() }
      } finally {
        pendingKeys.delete(key)
      }
    },
  }
}
