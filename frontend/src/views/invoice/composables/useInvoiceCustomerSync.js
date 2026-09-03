import { ref } from 'vue'
import { ElMessage } from 'element-plus'
import { syncInvoiceCustomerFromOkki } from '@/api/invoice'

// OKKI 客户手动同步弹框（镜像同步延迟时的自助入口）：
// 输入公司名 → 后端走 OKKI 客户查重+详情拉最新资料 → 弹框内展示同步结果
export function useInvoiceCustomerSync() {
  const visible = ref(false)
  const companyName = ref('')
  const loading = ref(false)
  const result = ref(null)

  function open() {
    companyName.value = ''
    result.value = null
    visible.value = true
  }

  async function submit() {
    const name = companyName.value.trim()
    if (!name) {
      ElMessage.warning('请输入客户公司名称')
      return
    }
    loading.value = true
    result.value = null
    try {
      const res = await syncInvoiceCustomerFromOkki({ company_name: name })
      result.value = res
      ElMessage.success(res.message || '客户信息已同步')
    } catch {
      // 拦截器已统一弹出后端 detail（未找到/多候选/OKKI 失败），留在弹框里改名重试
    } finally {
      loading.value = false
    }
  }

  return { visible, companyName, loading, result, open, submit }
}
