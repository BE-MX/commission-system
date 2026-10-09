import { reactive } from 'vue'
import { unlockUserAccount } from '@/api/userManagement'
import { confirmAction, msgError, msgSuccessText } from '@/utils/feedback'

export function useAccountUnlock(refreshList) {
  const unlockingIds = reactive(new Set())

  async function handleUnlockAccount(row) {
    if (unlockingIds.has(row.id)) return
    unlockingIds.add(row.id)
    try {
      await confirmAction(`确认解除「${row.real_name}（${row.username}）」的登录锁定？解锁后可使用原密码登录。`, '解锁账号', {
        confirmButtonText: '解锁账号', cancelButtonText: '取消', type: 'warning',
      })
    } catch {
      unlockingIds.delete(row.id)
      return
    }
    try {
      const result = await unlockUserAccount(row.id)
      row.login_locked = result.data.login_locked
      msgSuccessText(result.message)
      await refreshList()
    } catch (error) {
      msgError('账号解锁失败，请刷新后重试', error)
    } finally {
      unlockingIds.delete(row.id)
    }
  }

  return { unlockingIds, handleUnlockAccount }
}
