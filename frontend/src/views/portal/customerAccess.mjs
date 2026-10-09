// Invitation receipts permit exact replay. Versioned account/access edits do not.
export function createAccessMutation(send) {
  let state = 'idle', pending = null, generation = 0
  return {
    get state() { return state },
    get pending() { return pending && structuredClone(pending) },
    clear() { generation++; state = 'idle'; pending = null },
    async execute(value) {
      if (state === 'sending' || (state === 'uncertain' && value)) throw new Error('请先核对原操作结果。')
      if (!value && (pending?.action !== 'invite' || state !== 'uncertain')) throw new Error('此操作须读取当前状态后再处理，不能自动重试。')
      if (value) pending = structuredClone(value)
      const current = generation, wasUncertain = state === 'uncertain', operation = structuredClone(pending)
      state = 'sending'
      try {
        const result = await send(operation)
        if (current !== generation) return null
        const valid = operation.action === 'invite'
          ? result?.invitation_id && result?.event_id && typeof result.replayed === 'boolean'
          : result?.id === operation.id && Number.isSafeInteger(result.row_version) && result.row_version > operation.version
        if (!valid) throw new Error('服务器回执不完整，操作结果需要核对。')
        state = 'success'; pending = null
        return result
      } catch (error) {
        if (current !== generation) return null
        const status = error?.response?.status
        state = wasUncertain || !status || status >= 500 ? 'uncertain' : 'failed'
        if (state === 'failed') pending = null
        throw error
      }
    },
  }
}

export const accessStatuses = { draft: '待开通', enabled: '已启用', suspended: '已暂停', review_required: '身份待复核' }
export const accountStatuses = { invited: '待验证邮箱', active: '已激活', disabled: '已停用' }
export const invitationStatuses = { pending: '等待激活', consumed: '已使用', revoked: '已撤销', expired: '已过期' }
