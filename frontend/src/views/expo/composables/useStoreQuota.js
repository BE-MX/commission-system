/**
 * 当前账号绑定门店的额度快照（PC 线索台 / kiosk 共用，2026-08-06）。
 * 未绑定门店（quota.bound=false）是正常态：调用方据此隐藏额度展示，不报错。
 * pollMs > 0 时按间隔静默轮询（kiosk 现场需实时感知充值/消耗）。
 */
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { getMyStoreQuota } from '@/api/expo'

export function useStoreQuota({ kiosk = false, pollMs = 0 } = {}) {
  const quota = ref(null) // { bound, store_id, store_name, total_quota, used_quota, remaining }
  const loading = ref(false)
  let timer = null

  const fetchQuota = async () => {
    loading.value = true
    try {
      const res = await getMyStoreQuota({ kiosk })
      quota.value = res.data || { bound: false }
    } catch {
      // 静默：额度展示是辅助信息，网络抖动不打断试戴主流程；
      // 服务端硬阻断在 generate 端点，前端拿不到快照不影响安全口径
    } finally {
      loading.value = false
    }
  }

  onMounted(() => {
    fetchQuota()
    if (pollMs > 0) timer = setInterval(fetchQuota, pollMs)
  })
  onBeforeUnmount(() => { if (timer) clearInterval(timer) })

  return { quota, loading, fetchQuota }
}
