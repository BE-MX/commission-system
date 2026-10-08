// One immutable employee command until its explicit receipt is known.
// Read-after-write status is not evidence that this particular command succeeded.
export function createAdminCommand(send, { receiptField = 'request_id' } = {}) {
  if (!['request_id', 'access_id'].includes(receiptField)) throw new Error('无效回执对象类型。')
  let pending = null, state = 'idle', generation = 0
  return {
    get state() { return state },
    get pending() { return pending ? structuredClone(pending) : null },
    clear() { generation++; pending = null; state = 'idle' },
    async execute(command) {
      if (state === 'sending') throw new Error('操作正在提交，请等待。')
      if (state === 'uncertain' && command) throw new Error('上一操作结果待核对，请重试原命令。')
      if (command) pending = structuredClone(command)
      if (!pending) throw new Error('没有待处理命令。')
      const current = generation, wasUncertain = state === 'uncertain'
      state = 'sending'
      try {
        const result = await send(structuredClone(pending))
        if (current !== generation) return null
        if (!result?.original_receipt || result.original_receipt[receiptField] !== pending.id || !result.current_state) {
          const error = new Error('未收到有效操作回执，请重试原命令。')
          error.uncertain = true
          throw error
        }
        state = 'success'
        pending = null
        return result
      } catch (error) {
        if (current !== generation) return null
        const status = error?.response?.status
        state = wasUncertain || error.uncertain || !status || status >= 500 ? 'uncertain' : 'failed'
        if (state === 'failed') pending = null
        throw error
      }
    },
  }
}
